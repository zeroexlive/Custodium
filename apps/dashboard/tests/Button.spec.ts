import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import Button from '@/components/ui/Button.vue'

describe('Button', () => {
  it('renders its slot and defaults to type=button', () => {
    const wrapper = mount(Button, { slots: { default: 'Save' } })
    expect(wrapper.text()).toBe('Save')
    expect(wrapper.attributes('type')).toBe('button')
  })
  it('respects disabled and aria-label', () => {
    const wrapper = mount(Button, { props: { disabled: true, ariaLabel: 'Save changes' }, slots: { default: 'Save' } })
    expect(wrapper.attributes('disabled')).toBeDefined()
    expect(wrapper.attributes('aria-label')).toBe('Save changes')
  })
})
