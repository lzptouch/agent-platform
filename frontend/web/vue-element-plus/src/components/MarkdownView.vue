<template>
  <div class="md-body" v-html="rendered"></div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import MarkdownIt from 'markdown-it'
import DOMPurify from 'dompurify'
import hljs from 'highlight.js/lib/core'
import bash from 'highlight.js/lib/languages/bash'
import python from 'highlight.js/lib/languages/python'
import javascript from 'highlight.js/lib/languages/javascript'
import json from 'highlight.js/lib/languages/json'
import yaml from 'highlight.js/lib/languages/yaml'
import 'highlight.js/styles/github-dark.css'

hljs.registerLanguage('bash', bash)
hljs.registerLanguage('python', python)
hljs.registerLanguage('javascript', javascript)
hljs.registerLanguage('js', javascript)
hljs.registerLanguage('json', json)
hljs.registerLanguage('yaml', yaml)

const props = defineProps<{ text: string }>()

const md = new MarkdownIt({
  html: false,
  linkify: true,
  breaks: false,
  highlight(str: string, lang: string): string {
    if (lang && hljs.getLanguage(lang)) {
      try { return hljs.highlight(str, { language: lang, ignoreIllegals: true }).value }
      catch { /* */ }
    }
    return ''
  },
})

const rendered = computed(() => {
  const raw = md.render(props.text ?? '')
  return DOMPurify.sanitize(raw, {
    ADD_ATTR: ['target'],
    FORBID_TAGS: ['style', 'iframe', 'form'],
  })
})
</script>

<style scoped>
.md-body { font-size: 14px; line-height: 1.7; }
.md-body :deep(h1), .md-body :deep(h2), .md-body :deep(h3) { margin: 1em 0 0.5em; }
.md-body :deep(p) { margin: 0.6em 0; }
.md-body :deep(pre) {
  background: var(--bg-code);
  color: #e6e8eb;
  padding: 12px 14px;
  border-radius: var(--radius-sm);
  overflow-x: auto;
}
.md-body :deep(code) {
  background: var(--bg-code);
  padding: 2px 6px;
  border-radius: 4px;
  font-family: var(--font-mono);
  font-size: 12.5px;
}
.md-body :deep(pre code) { background: transparent; padding: 0; }
.md-body :deep(a) { color: var(--accent); }
.md-body :deep(table) { border-collapse: collapse; }
.md-body :deep(th), .md-body :deep(td) { border: 1px solid var(--border); padding: 6px 10px; }
.md-body :deep(blockquote) {
  border-left: 3px solid var(--accent);
  margin: 0.6em 0;
  padding: 4px 12px;
  color: var(--text-dim);
}
</style>