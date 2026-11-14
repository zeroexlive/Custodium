<script setup lang="ts">
import Card from '@/components/ui/Card.vue'
</script>
<template>
  <main class="min-h-screen flex items-center justify-center p-4">
    <Card title="Registration is closed" class="w-full max-w-md">
      <p class="text-sm text-ink-muted">
        Custodium accounts are not self-service. The platform owner and
        global administrators create customer accounts and send the login
        credentials — if you need an account, contact your platform
        administrator.
      </p>
      <p class="mt-4 text-sm">
        Already have credentials?
        <RouterLink to="/login" class="underline">Log in</RouterLink>
      </p>
    </Card>
  </main>
</template>
