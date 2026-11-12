//! `mpc-eval` — Phase 3 evaluation driver binary.
//!
//! **TEST-ONLY.** Runs the FROST and CGGMP24 evaluation ceremonies
//! with ephemeral in-memory keys and prints the resulting group
//! public keys and signature-verification outcomes. It refuses to
//! run unless `CUSTODIUM_MPC_EVAL=1` is set, persists nothing, opens
//! no sockets, and must never be deployed as or alongside a signer.

use custodium_mpc_eval_harness::{ecdsa_eval, frost_eval};
use frost_ed25519 as frost;

fn hex(bytes: &[u8]) -> String {
    bytes.iter().map(|b| format!("{b:02x}")).collect()
}

fn main() {
    if std::env::var("CUSTODIUM_MPC_EVAL").as_deref() != Ok("1") {
        eprintln!(
            "mpc-eval is a TEST-ONLY evaluation tool. \
             Set CUSTODIUM_MPC_EVAL=1 to run it. Refusing to run."
        );
        std::process::exit(2);
    }

    println!("== FROST Ed25519 evaluation (frost-ed25519 3.0.0, 2-of-3 DKG) ==");
    let (key_packages, pubkey_package) =
        frost_eval::run_dkg(3, 2).expect("FROST DKG failed");
    let message = b"custodium phase 3 evaluation (binary run)";
    let signer_ids: Vec<frost::Identifier> = [1u16, 3u16]
        .iter()
        .map(|i| frost::Identifier::try_from(*i).expect("valid identifier"))
        .collect();
    let signature = frost_eval::threshold_sign_with_package(
        &key_packages,
        &pubkey_package,
        &signer_ids,
        message,
    )
    .expect("FROST threshold signing failed");
    let vk_bytes = pubkey_package
        .verifying_key()
        .serialize()
        .expect("serialize verifying key");
    println!("group verifying key: {}", hex(&vk_bytes));
    println!(
        "signature: {}",
        hex(&signature.serialize().expect("serialize signature"))
    );
    println!("verified against group key by the FROST library: OK");

    println!();
    println!("== CGGMP24 ECDSA evaluation (cggmp24 0.7.0-alpha.2, 2-of-3) ==");
    println!("(aux-info generation with safe primes can take a while)");
    let runtime = tokio::runtime::Builder::new_multi_thread()
        .enable_all()
        .build()
        .expect("tokio runtime");
    let output = runtime
        .block_on(ecdsa_eval::run_ceremony(3, 2, &[0, 2], message))
        .expect("CGGMP24 ceremony failed");
    println!("shared public key (SEC1): {}", hex(&output.public_key_sec1));
    println!("signature r: {}", hex(&output.signature_r));
    println!("signature s: {}", hex(&output.signature_s));
    println!("verified inside the library (Signature::verify): OK");
    println!();
    println!("All evaluation ceremonies completed. Keys were ephemeral and are gone.");
}
