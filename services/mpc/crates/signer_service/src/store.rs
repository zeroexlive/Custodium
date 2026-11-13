//! Encrypted share storage.
//!
//! Every secret artifact (ECDSA key share, FROST key package, ECDSA
//! aux info) is serialized, then encrypted with XChaCha20-Poly1305
//! under this node's own 32-byte store key before it touches disk.
//! Public metadata (curve, threshold, group public key) is stored
//! as plaintext JSON — public keys are not secrets. Files are
//! written atomically (temp file + rename). A wrong key or a
//! tampered file fails AEAD verification and is a hard error:
//! the node refuses to operate on that key (fail closed).

use std::fs;
use std::path::{Path, PathBuf};

use chacha20poly1305::aead::{Aead, KeyInit, Payload};
use chacha20poly1305::{XChaCha20Poly1305, XNonce};
use rand::RngCore;

use crate::{err, SvcResult};

const NONCE_LEN: usize = 24;

/// Validate an externally supplied key id before using it as a
/// file name component (no separators, no traversal).
pub fn validate_key_id(key_id: &str) -> SvcResult<()> {
    if key_id.is_empty()
        || key_id.len() > 128
        || !key_id
            .chars()
            .all(|c| c.is_ascii_alphanumeric() || matches!(c, '-' | '_' | '.'))
        || key_id.contains("..")
    {
        return Err(format!("invalid key_id: {key_id:?}"));
    }
    Ok(())
}

/// One node's encrypted store.
pub struct ShareStore {
    dir: PathBuf,
    cipher: XChaCha20Poly1305,
}

impl ShareStore {
    /// Open (creating if needed) the store directory and load the
    /// encryption key from `key_file` (64 hex chars or 32 raw bytes).
    pub fn open(dir: &Path, key_file: &Path) -> SvcResult<Self> {
        fs::create_dir_all(dir).map_err(err)?;
        let raw = fs::read(key_file).map_err(|e| {
            format!("cannot read store key file {}: {e}", key_file.display())
        })?;
        let key_bytes: Vec<u8> = if raw.len() == 32 {
            raw.clone()
        } else {
            let text = String::from_utf8_lossy(&raw);
            let text = text.trim();
            if text.len() == 64 {
                hex::decode(text).map_err(|_| "store key file is not valid hex")?
            } else {
                return Err(
                    "store key file must contain 32 raw bytes or 64 hex chars".into(),
                );
            }
        };
        let cipher = XChaCha20Poly1305::new(key_bytes.as_slice().into());
        Ok(Self {
            dir: dir.to_path_buf(),
            cipher,
        })
    }

    fn enc_path(&self, name: &str) -> PathBuf {
        self.dir.join(format!("{name}.enc"))
    }

    fn meta_path(&self, name: &str) -> PathBuf {
        self.dir.join(format!("{name}.json"))
    }

    /// Encrypt and persist a secret artifact.
    pub fn save_secret(&self, name: &str, plaintext: &[u8]) -> SvcResult<()> {
        let mut nonce = [0u8; NONCE_LEN];
        rand::rngs::OsRng.fill_bytes(&mut nonce);
        let ct = self
            .cipher
            .encrypt(
                XNonce::from_slice(&nonce),
                Payload {
                    msg: plaintext,
                    aad: name.as_bytes(),
                },
            )
            .map_err(|_| "share encryption failed")?;
        let mut blob = Vec::with_capacity(NONCE_LEN + ct.len());
        blob.extend_from_slice(&nonce);
        blob.extend_from_slice(&ct);
        write_atomic(&self.enc_path(name), &blob)
    }

    /// Load and decrypt a secret artifact; `Ok(None)` if absent.
    pub fn load_secret(&self, name: &str) -> SvcResult<Option<Vec<u8>>> {
        let path = self.enc_path(name);
        if !path.exists() {
            return Ok(None);
        }
        let blob = fs::read(&path).map_err(err)?;
        if blob.len() <= NONCE_LEN {
            return Err(format!("corrupt share file for {name}"));
        }
        let (nonce, ct) = blob.split_at(NONCE_LEN);
        let pt = self
            .cipher
            .decrypt(
                XNonce::from_slice(nonce),
                Payload {
                    msg: ct,
                    aad: name.as_bytes(),
                },
            )
            .map_err(|_| {
                format!("share decryption failed for {name} (wrong store key or tampered file)")
            })?;
        Ok(Some(pt))
    }

    /// Persist public metadata (JSON text).
    pub fn save_public(&self, name: &str, json: &str) -> SvcResult<()> {
        write_atomic(&self.meta_path(name), json.as_bytes())
    }

    /// Load public metadata; `Ok(None)` if absent.
    pub fn load_public(&self, name: &str) -> SvcResult<Option<String>> {
        let path = self.meta_path(name);
        if !path.exists() {
            return Ok(None);
        }
        Ok(Some(fs::read_to_string(&path).map_err(err)?))
    }

    /// Whether a secret artifact exists.
    pub fn has_secret(&self, name: &str) -> bool {
        self.enc_path(name).exists()
    }
}

fn write_atomic(path: &Path, bytes: &[u8]) -> SvcResult<()> {
    let tmp = path.with_extension("tmp");
    fs::write(&tmp, bytes).map_err(err)?;
    fs::rename(&tmp, path).map_err(err)?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn store_in(dir: &Path, key_hex: &str) -> ShareStore {
        let key_file = dir.join("store.key");
        fs::write(&key_file, key_hex).expect("write key");
        ShareStore::open(&dir.join("store"), &key_file).expect("open store")
    }

    fn tempdir() -> PathBuf {
        let d = std::env::temp_dir().join(format!("signer-store-{}", uuid::Uuid::new_v4()));
        fs::create_dir_all(&d).expect("mkdir");
        d
    }

    #[test]
    fn secret_round_trip_and_wrong_key_fails() {
        let dir = tempdir();
        let key_a = "11".repeat(32);
        let store = store_in(&dir, &key_a);
        store.save_secret("ecdsa-wallet-1", b"share-bytes").expect("save");
        assert_eq!(
            store.load_secret("ecdsa-wallet-1").expect("load"),
            Some(b"share-bytes".to_vec())
        );
        // A different store key must NOT decrypt the share.
        let other = store_in(&dir, &"22".repeat(32));
        // (different store dir) — reopen the SAME dir with key B:
        let key_file_b = dir.join("store.key");
        let same_dir_wrong_key =
            ShareStore::open(&dir.join("store"), &key_file_b).expect("open");
        drop(other);
        assert!(same_dir_wrong_key.load_secret("ecdsa-wallet-1").is_err());
        // Tampering with the ciphertext must fail AEAD verification.
        let path = dir.join("store").join("ecdsa-wallet-1.enc");
        let mut blob = fs::read(&path).expect("read");
        let last = blob.len() - 1;
        blob[last] ^= 0x01;
        fs::write(&path, blob).expect("tamper");
        assert!(store.load_secret("ecdsa-wallet-1").is_err());
    }

    #[test]
    fn key_id_validation() {
        assert!(validate_key_id("wallet-abc_1.2").is_ok());
        assert!(validate_key_id("../etc/passwd").is_err());
        assert!(validate_key_id("a/b").is_err());
        assert!(validate_key_id("").is_err());
    }
}
