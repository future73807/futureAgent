import React from 'react'

/**
 * 品牌标记。
 *
 * 与 public/icon.svg 是同一份图形（近黑圆角方块 + 白色终端提示符），
 * 但内联成组件：favicon 那一份浏览器自己会画，界面里这一份要跟着主题走、
 * 也要能自由改尺寸，所以不用 <img src="/icon.svg">。
 *
 * 刻意不用渐变、不用彩色——整套界面只有黑、白、灰三阶。
 */
export default function BrandMark({ size = 26, className = '' }) {
  return (
    <svg
      className={className}
      width={size}
      height={size}
      viewBox="0 0 64 64"
      role="img"
      aria-label="futureAgent"
      focusable="false"
    >
      <rect width="64" height="64" rx="16" className="brand-mark-bg" />
      <path
        d="M20 22 L31 32 L20 42"
        fill="none"
        strokeWidth="6"
        strokeLinecap="round"
        strokeLinejoin="round"
        className="brand-mark-fg"
      />
      <rect x="35" y="38" width="11" height="5.5" rx="2.75" className="brand-mark-fg" />
    </svg>
  )
}
