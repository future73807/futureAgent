// AI 回复的 Markdown 渲染：marked 解析 + DOMPurify 白名单净化。
import { marked } from 'marked'
import DOMPurify from 'dompurify'

marked.setOptions({ breaks: true, gfm: true })

// 外部链接统一新窗口打开并携带 rel，防止反向标签注入
DOMPurify.addHook('afterSanitizeAttributes', (node) => {
  if (node.tagName === 'A' && node.getAttribute('href')) {
    node.setAttribute('target', '_blank')
    node.setAttribute('rel', 'noopener noreferrer nofollow')
  }
})

export function renderMarkdown(text) {
  const raw = marked.parse(String(text ?? ''))
  return DOMPurify.sanitize(raw, {
    ALLOWED_TAGS: [
      'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
      'p', 'br', 'hr', 'blockquote',
      'ul', 'ol', 'li',
      'a', 'strong', 'em', 'del', 'code', 'pre', 'kbd',
      'table', 'thead', 'tbody', 'tr', 'th', 'td',
      'img', 'sup', 'sub', 'span', 'input',
    ],
    ALLOWED_ATTR: ['href', 'title', 'src', 'alt', 'class', 'type', 'checked', 'disabled', 'target', 'rel'],
    FORBID_ATTR: ['style', 'onerror', 'onclick', 'onload'],
  })
}
