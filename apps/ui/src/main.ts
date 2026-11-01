import { createApp } from 'vue'

import { loadUploadPolicy } from '@/api/upload-policy'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import 'element-plus/theme-chalk/dark/css-vars.css'

import App from './App.vue'
import router from './router'
import { useDesktopStore } from '@/stores/desktop'
import './styles/tokens.css'

const app = createApp(App)
const pinia = createPinia()
app.use(pinia)
app.use(router)
app.use(ElementPlus)
// P4-04：上传白名单以**后端**为准（拉取失败则用本地兜底）
void loadUploadPolicy()
app.mount('#app')

// 桌面端能力探测（Web 形态下 no-op）
void useDesktopStore(pinia).refresh()