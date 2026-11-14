<script setup lang="ts">
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import Button from '@/components/ui/Button.vue'
import Input from '@/components/ui/Input.vue'
import Card from '@/components/ui/Card.vue'

const email = ref(''); const password = ref(''); const code = ref('')
const error = ref<string | null>(null)
const step = ref<'credentials' | 'totp'>('credentials')
const auth = useAuthStore(); const router = useRouter(); const route = useRoute()

function destination(): string {
  const target = route.query.redirect
  return typeof target === 'string' && target.startsWith('/') ? target : '/'
}

async function submit(): Promise<void> {
  error.value = null
  try {
    const outcome = await auth.login(email.value, password.value)
    if (outcome === 'totp') { step.value = 'totp'; return }
    await router.push(destination())
  } catch (e) { error.value = e instanceof Error ? e.message : 'Login failed' }
}

async function submitCode(): Promise<void> {
  error.value = null
  try { await auth.completeTotp(code.value.trim()); await router.push(destination()) }
  catch (e) { error.value = e instanceof Error ? e.message : 'Two-factor verification failed' }
}
</script>
<template>
  <main class="min-h-screen flex items-center justify-center p-4">
    <Card title="Log in to Custodium" class="w-full max-w-md">
      <form v-if="step === 'credentials'" class="space-y-4" @submit.prevent="submit">
        <Input id="email" v-model="email" label="Email" type="email" required autocomplete="email" />
        <Input id="password" v-model="password" label="Password" type="password" required autocomplete="current-password" />
        <p v-if="error" role="alert" class="text-sm text-danger">{{ error }}</p>
        <Button type="submit" :disabled="auth.loading">Log in</Button>
        <p class="text-sm text-ink-muted">
          Accounts are created by the Custodium platform team — there is no
          public sign-up. If you need an account, ask your platform
          administrator to create one and send you your credentials.
        </p>
      </form>
      <form v-else class="space-y-4" @submit.prevent="submitCode">
        <p class="text-sm text-ink-muted">
          This account has two-factor authentication enabled. Enter the
          6-digit code from your authenticator app, or one of your
          recovery codes.
        </p>
        <Input id="totp-code" v-model="code" label="Two-factor code" required autocomplete="one-time-code" />
        <p v-if="error" role="alert" class="text-sm text-danger">{{ error }}</p>
        <Button type="submit" :disabled="auth.loading">Verify and log in</Button>
        <p class="text-sm">
          <button type="button" class="underline" @click="step = 'credentials'">Back to sign in</button>
        </p>
      </form>
    </Card>
  </main>
</template>
