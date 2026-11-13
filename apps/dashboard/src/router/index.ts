import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const routes: RouteRecordRaw[] = [
  { path: '/login', name: 'login', component: () => import('@/features/authentication/LoginView.vue'), meta: { public: true } },
  { path: '/register', name: 'register', component: () => import('@/features/authentication/RegisterView.vue'), meta: { public: true } },
  {
    path: '/', component: () => import('@/layouts/DashboardLayout.vue'),
    children: [
      { path: '', name: 'overview', component: () => import('@/features/overview/OverviewView.vue') },
      { path: 'organizations', name: 'organizations', component: () => import('@/features/organizations/OrganizationsView.vue') },
      { path: 'projects', name: 'projects', component: () => import('@/features/projects/ProjectsView.vue') },
      { path: 'api-keys', name: 'api-keys', component: () => import('@/features/api_keys/ApiKeysView.vue') },
      { path: 'security', name: 'security', component: () => import('@/features/security/SecurityView.vue') },
      { path: 'wallets', name: 'wallets', component: () => import('@/features/wallets/WalletsView.vue') },
      { path: 'addresses', name: 'addresses', component: () => import('@/features/addresses/AddressesView.vue') },
      { path: 'transactions', name: 'transactions', component: () => import('@/features/transaction_explorer/TransactionExplorerView.vue') },
      { path: 'assets', name: 'assets', component: () => import('@/features/assets/AssetsView.vue') },
      { path: 'sweeps', name: 'sweeps', component: () => import('@/features/sweeps/SweepsView.vue') },
      { path: 'sweep-endpoint', name: 'sweep-endpoint', component: () => import('@/features/sweeps/SweepEndpointView.vue') },
      { path: 'sweep-settings', name: 'sweep-settings', component: () => import('@/features/sweeps/SweepSettingsView.vue') },
      { path: 'address-book', name: 'address-book', component: () => import('@/features/addressbook/AddressBookView.vue') },
      { path: 'deposit-policies', name: 'deposit-policies', component: () => import('@/features/deposits/DepositPoliciesView.vue') },
      { path: 'gas-station', name: 'gas-station', component: () => import('@/features/sweeps/GasStationView.vue') },
      { path: 'blacklist', name: 'blacklist', component: () => import('@/features/blacklist/BlacklistView.vue') },
      { path: 'withdrawals', name: 'withdrawals', component: () => import('@/features/withdrawals/WithdrawalsView.vue') },
      { path: 'webhooks', name: 'webhooks', component: () => import('@/features/webhooks/WebhooksView.vue') },
      { path: 'billing', name: 'billing', component: () => import('@/features/billing/BillingView.vue') },
      { path: 'team', name: 'team', component: () => import('@/features/team/TeamView.vue') },
      { path: 'webhooks', name: 'webhooks', component: () => import('@/features/webhooks/WebhooksView.vue') },
      { path: 'audit', name: 'audit', component: () => import('@/features/audit/AuditView.vue') },
    ],
  },
  { path: '/:pathMatch(.*)*', redirect: '/' },
]

const router = createRouter({ history: createWebHistory(), routes })

router.beforeEach((to) => {
  const auth = useAuthStore()
  // Cookie-based sessions may exist without a stored token, so only
  // redirect-away from auth pages when we positively know we're signed in.
  if (to.meta.public) return true
  // Protected pages render their own API errors; if there is no session
  // hint at all, send the user to login.
  const hasSessionHint = auth.isAuthenticated || document.cookie.length > 0
  if (!hasSessionHint && !import.meta.env.DEV) return { name: 'login' }
  return true
})

export default router
