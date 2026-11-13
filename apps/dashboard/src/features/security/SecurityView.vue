<script setup lang="ts">
import { computed, ref } from 'vue'
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { api } from '@/api/client'
import type { TotpSetup } from '@/api/types'
import Button from '@/components/ui/Button.vue'
import Card from '@/components/ui/Card.vue'
import Badge from '@/components/ui/Badge.vue'
import Input from '@/components/ui/Input.vue'

const client = useQueryClient()
const me = useQuery({ queryKey: ['me'], queryFn: api.me })
const enabled = computed(() => me.data.value?.totp_enabled === true)

const setupData = ref<TotpSetup | null>(null)
const code = ref('')
const disableCode = ref('')
const recoveryCodes = ref<string[]>([])
const error = ref('')
const notice = ref('')

const setup = useMutation({
  mutationFn: () => api.totpSetup(),
  onSuccess: (data) => { setupData.value = data; error.value = ''; notice.value = '' },
  onError: (e) => { error.value = e instanceof Error ? e.message : 'Setup failed' },
})
const enable = useMutation({
  mutationFn: () => api.totpEnable(code.value.trim()),
  onSuccess: (data) => {
    recoveryCodes.value = data.recovery_codes
    setupData.value = null; code.value = ''
    notice.value = 'Two-factor authentication is on. Store the recovery codes below somewhere safe — they are shown only once.'
    void client.invalidateQueries({ queryKey: ['me'] })
  },
  onError: (e) => { error.value = e instanceof Error ? e.message : 'Enable failed' },
})
const disable = useMutation({
  mutationFn: () => api.totpDisable(disableCode.value.trim()),
  onSuccess: () => {
    disableCode.value = ''; recoveryCodes.value = []
    notice.value = 'Two-factor authentication is off.'
    void client.invalidateQueries({ queryKey: ['me'] })
  },
  onError: (e) => { error.value = e instanceof Error ? e.message : 'Disable failed' },
})
</script>

<template>
  <div class="space-y-6">
    <div>
      <h1 class="text-2xl font-semibold">Security</h1>
      <p class="text-sm text-ink-muted">
        Two-factor authentication (TOTP) for your dashboard account. When it is on,
        signing in asks for a 6-digit authenticator code after your password.
      </p>
    </div>

    <p v-if="error" role="alert" class="text-sm text-danger">{{ error }}</p>
    <p v-if="notice" class="text-sm text-success">{{ notice }}</p>

    <Card title="Two-factor authentication">
      <div class="flex items-center gap-3">
        <span class="text-sm">Status:</span>
        <Badge :tone="enabled ? 'success' : 'neutral'">{{ enabled ? 'Enabled' : 'Not enabled' }}</Badge>
      </div>

      <div v-if="!enabled" class="mt-4 space-y-4">
        <Button v-if="!setupData" :disabled="setup.isPending.value" @click="setup.mutate()">Set up two-factor authentication</Button>
        <div v-else class="space-y-3">
          <p class="text-sm">
            Add this secret to your authenticator app (or open the provisioning URI on the
            device), then enter the 6-digit code it shows to finish enabling.
          </p>
          <p class="text-sm"><span class="text-ink-muted">Secret:</span> <code class="break-all">{{ setupData.secret }}</code></p>
          <p class="text-sm"><span class="text-ink-muted">Provisioning URI:</span> <code class="break-all">{{ setupData.provisioning_uri }}</code></p>
          <form class="flex flex-wrap items-end gap-3" @submit.prevent="enable.mutate()">
            <Input id="totp-enable-code" v-model="code" label="Authenticator code" required autocomplete="one-time-code" />
            <Button type="submit" :disabled="enable.isPending.value">Enable</Button>
          </form>
        </div>
      </div>

      <div v-else class="mt-4 space-y-3">
        <form class="flex flex-wrap items-end gap-3" @submit.prevent="disable.mutate()">
          <Input id="totp-disable-code" v-model="disableCode" label="Current code or a recovery code" required autocomplete="one-time-code" />
          <Button type="submit" variant="danger" :disabled="disable.isPending.value">Disable two-factor authentication</Button>
        </form>
      </div>

      <div v-if="recoveryCodes.length" class="mt-4 space-y-2">
        <p class="text-sm font-medium">Recovery codes — shown once, store them now:</p>
        <ul class="grid grid-cols-2 gap-1 font-mono text-sm md:grid-cols-4">
          <li v-for="rc in recoveryCodes" :key="rc">{{ rc }}</li>
        </ul>
      </div>
    </Card>
  </div>
</template>
