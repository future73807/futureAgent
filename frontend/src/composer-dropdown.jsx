import { createContext, useCallback, useContext, useMemo, useState } from 'react'

const ComposerDropdownContext = createContext(null)

/**
 * 输入卡动作行里的下拉共用"同时只开一个"的槽位。
 *
 * 每个 chip 各自持有 `open` 时，先点 A 再点 B 会留下两个面板同时挂在页面上：
 * antd 的**受控** Dropdown 并不保证外部点击一定回调 `onOpenChange(false)`，
 * 于是旧面板压在新面板上面，用户看到的是"点了没反应/点不出来"，更糟的是接着
 * 点列表项会落到错误的那个面板里。
 *
 * 与其依赖"外部点击一定会关掉别人"这个假设，不如让"只开一个"成为结构上的
 * 事实：所有 chip 读写同一个 openId。
 */
export function ComposerDropdownProvider({ children }) {
  const [openId, setOpenId] = useState('')
  const value = useMemo(() => ({ openId, setOpenId }), [openId])
  return <ComposerDropdownContext.Provider value={value}>{children}</ComposerDropdownContext.Provider>
}

/**
 * 取某个 chip 的开合状态。
 *
 * 没有 Provider 时退化成组件自己的局部状态：这样单独复用某个 chip（管理端
 * 预览、单测渲染）不会变成一个永远打不开的下拉。
 */
export function useComposerDropdown(id) {
  const context = useContext(ComposerDropdownContext)
  const [localOpen, setLocalOpen] = useState(false)

  const setOpen = useCallback((next) => {
    if (!context) {
      setLocalOpen(Boolean(next))
      return
    }
    context.setOpenId((current) => {
      if (next) return id
      return current === id ? '' : current
    })
  }, [context, id])

  if (!context) return [localOpen, setOpen]
  return [context.openId === id, setOpen]
}
