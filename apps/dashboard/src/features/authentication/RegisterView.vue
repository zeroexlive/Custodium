<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import Button from '@/components/ui/Button.vue'
import Input from '@/components/ui/Input.vue'
import Card from '@/components/ui/Card.vue'

const email = ref(''); const password = ref(''); const displayName = ref(''); const error = ref<string | null>(null)
const notice = ref<string | null>(null)
const auth = useAuthStore(); const router = useRouter()
async function submit(): Promise<void> {
  error.value = null
  try {
    await auth.register(email.value, password.value, displayName.value || undefined)
    notice.value = 'Account created. Check your email to verify it, then log in.'
    await router.push('/login')
  } catch (e) { error.value = e instanceof Error ? e.message : 'Registration failed' }
}
</script>
<template>
  <main class="min-h-screen flex items-center justify-center p-4">
    <Card title="Create a Custodium account" class="w-full max-w-md">
      <form class="space-y-4" @submit.prevent="submit">
        <Input id="display-name" v-model="displayName" label="Display name (optional)" autocomplete="name" />
        <Input id="reg-email" v-model="email" label="Email" type="email" required autocomplete="email" />
        <Input id="reg-password" v-model="password" label="Password" type="password" required autocomplete="new-password" />
        <p v-if="error" role="alert" class="text-sm text-danger">{{ error }}</p>
        <p v-if="notice" role="status" class="text-sm">{{ notice }}</p>
        <Button type="submit" :disabled="auth.loading">Register</Button>
        <p class="text-sm">Already registered? <RouterLink to="/login" class="underline">Log in</RouterLink></p>
      </form>
    </Card>
  </main>
</template>
