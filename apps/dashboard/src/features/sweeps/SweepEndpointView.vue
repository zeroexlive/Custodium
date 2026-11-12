<script setup lang="ts">
import { ref } from 'vue'
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { api } from '@/api/client'
import Button from '@/components/ui/Button.vue'
import Input from '@/components/ui/Input.vue'
import Card from '@/components/ui/Card.vue'

const endpointUrl = ref('')
const client = useQueryClient()
const query = useQuery({ queryKey: ['sweep-endpoint'], queryFn: api.getSweepEndpoint, retry: false })
const save = useMutation({
  mutationFn: () => api.putSweepEndpoint(endpointUrl.value.trim()),
  onSuccess: async () => { await client.invalidateQueries({ queryKey: ['sweep-endpoint'] }) },
})
const remove = useMutation({
  mutationFn: () => api.deleteSweepEndpoint(),
  onSuccess: async () => { endpointUrl.value = ''; await client.invalidateQueries({ queryKey: ['sweep-endpoint'] }) },
})
function submit(): void { if (endpointUrl.value.trim().startsWith('https://')) save.mutate() }
</script>
<template>
  <div class="space-y-6">
    <h1 class="text-2xl font-semibold">External Sweep Destination Endpoint</h1>
    <p class="text-ink-muted">Register one HTTPS endpoint per project. Before each sweep, Custodium calls it (with network / asset headers) and expects exactly one plain-text wallet address in the response. Destinations are never supplied in sweep requests or read from local files. Backend enforcement is Phase 10; this form is wired to <code class="font-mono text-sm">PUT /api/v1/sweep-destination-endpoint</code>.</p>
    <Card title="Registered endpoint">
      <p v-if="query.isPending.value">Loading…</p>
      <p v-else-if="query.data.value?.endpoint_url" class="font-mono text-sm break-all">{{ query.data.value.endpoint_url }}</p>
      <p v-else class="text-sm text-ink-muted">No endpoint registered yet (or the Phase 10 backend is not available).</p>
      <form class="space-y-4 mt-4" @submit.prevent="submit">
        <Input id="sweep-endpoint-url" v-model="endpointUrl" label="Endpoint URL (HTTPS only)" type="url" required placeholder="https://exchange.example.com/api/hot-wallet" />
        <div class="flex gap-2">
          <Button type="submit" :disabled="save.isPending.value">Save endpoint</Button>
          <Button type="button" variant="danger" @click="remove.mutate()">Disable / remove</Button>
        </div>
        <p v-if="endpointUrl && !endpointUrl.startsWith('https://')" role="alert" class="text-sm text-danger">HTTPS is required.</p>
        <p v-if="save.isError.value" role="alert" class="text-sm text-danger">{{ (save.error.value as Error).message }}</p>
        <p v-if="save.isSuccess.value" role="status" class="text-sm text-success">Endpoint saved.</p>
      </form>
    </Card>
  </div>
</template>
