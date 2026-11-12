<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import Button from '@/components/ui/Button.vue'
import Input from '@/components/ui/Input.vue'
import Card from '@/components/ui/Card.vue'

const email = ref(''); const password = ref(''); const error = ref<string | null>(null)
const auth = useAuthStore(); const router = useRouter()
async function submit(): Promise<void> {
  error.value = null
  try { await auth.login(email.value, password.value); await router.push('/') }
  catch (e) { error.value = e instanceof Error ? e.message : 'Login failed' }
}
</script>
<template>
  <main class="min-h-screen flex items-center justify-center p-4">
    <Card title="Log in to Custodium" class="w-full max-w-md">
      <form class="space-y-4" @submit.prevent="submit">
        <Input id="email" v-model="email" label="Email" type="email" required autocomplete="email" />
        <Input id="password" v-model="password" label="Password" type="password" required autocomplete="current-password" />
        <p v-if="error" role="alert" class="text-sm text-danger">{{ error }}</p>
        <Button type="submit" :disabled="auth.loading">Log in</Button>
        <p class="text-sm">No account? <RouterLink to="/register" class="underline">Register</RouterLink></p>
      </form>
    </Card>
  </main>
</template>
