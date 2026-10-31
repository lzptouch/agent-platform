/** P4-05 · 引用适配器的单元测试（两种来源都覆盖）。 */
import { describe, expect, it } from 'vitest'

import {
  adaptRagReferences,
  adaptReferenceCards,
  mergeCitations,
  type Citation,
} from '@/api/citations'

describe('P4-05 · RAG 引用适配器', () => {
  it('字符串条目 → 标题取片段、原文作摘要', () => {
    const out = adaptRagReferences(['这是一段检索到的原文'])
    expect(out).toHaveLength(1)
    expect(out[0].source).toBe('rag')
    expect(out[0].snippet).toContain('检索到的原文')
  })

  it('对象条目 → 提取 title / url / snippet', () => {
    const out = adaptRagReferences([
      { title: '文档 A', url: 'https://a', content: '正文' },
    ])
    expect(out[0].title).toBe('文档 A')
    expect(out[0].url).toBe('https://a')
    expect(out[0].snippet).toBe('正文')
  })

  it('非数组输入 → 空数组（不抛错）', () => {
    expect(adaptRagReferences(undefined)).toEqual([])
    expect(adaptRagReferences('x')).toEqual([])
  })
})

describe('P4-05 · Web Research 引用适配器', () => {
  it('titles 数组 → 取第一个作为标题', () => {
    const out = adaptReferenceCards([
      { titles: ['网页标题', '备用'], url: 'https://w', content: '网页正文' },
    ])
    expect(out[0].title).toBe('网页标题')
    expect(out[0].url).toBe('https://w')
    expect(out[0].source).toBe('web')
  })

  it('缺字段时用序号兜底', () => {
    const out = adaptReferenceCards([{}])
    expect(out[0].title).toBe('引用 1')
  })
})

describe('P4-05 · 合并与序号', () => {
  it('mergeCitations 让序号连续', () => {
    const merged = mergeCitations(
      adaptRagReferences(['a']),
      adaptReferenceCards([{ titles: ['t'], url: 'u' }]),
    )
    expect(merged.map((c: Citation) => c.index)).toEqual([1, 2])
    expect(merged[0].source).toBe('rag')
    expect(merged[1].source).toBe('web')
  })

  it('两种来源渲染出的字段集一致（外观可统一）', () => {
    const rag = adaptRagReferences(['a'])[0]
    const web = adaptReferenceCards([{ titles: ['t'], url: 'u' }])[0]
    expect(Object.keys(rag).sort()).toEqual(Object.keys(web).sort())
  })
})
