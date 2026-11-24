import vue from 'eslint-plugin-vue'
import { withVueTs, vueTsConfigs } from '@vue/eslint-config-typescript'

export default withVueTs(
  vue.configs['flat/essential'],
  vueTsConfigs.recommended,
)
