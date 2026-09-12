import React, { useEffect, useState } from 'react'
import Select from 'antd/es/select'
import Tooltip from 'antd/es/tooltip'
import { apiFetch } from '../api.js'
import { permissionModeHint, permissionModeName, permissionModes } from '../ui-labels.js'

function readableError(error) {
  return error?.detail || error?.message || '请求失败，请检查网络或稍后重试。'
}

const options = permissionModes.map((mode) => ({
  value: mode,
  label: permissionModeName(mode),
  title: permissionModeHint(mode),
}))

/**
 * 侧边栏常驻的权限档位选择器。
 *
 * 档位影响每一次执行要不要人工确认，属于高频开关；原先它埋在工作区设置页，
 * 用户执行前想改一次要跳三个页面。这里与设置页共享 workspace.permission_mode
 * 与 onUpdated 回调，两处改动都会即时反映到对方。
 */
export default function PermissionModeChip({ workspace, canWrite = true, onUpdated, messageApi }) {
  const [mode, setMode] = useState(workspace?.permission_mode || 'default')
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    // 以服务端为准：设置页或另一端改了档位，这里要跟着变。
    setMode(workspace?.permission_mode || 'default')
  }, [workspace?.id, workspace?.permission_mode])

  const change = async (next) => {
    const previous = mode
    setMode(next)
    setSaving(true)
    try {
      // 后端 PermissionModeRequest 的字段名是 permission_mode，不是 mode。
      const payload = await apiFetch(`/api/v1/workspaces/${workspace.id}/permission-mode`, { method: 'PUT', body: JSON.stringify({ permission_mode: next }) })
      messageApi?.success(next === 'full_access' ? '已开启完全访问，工具将直接执行且不可逆' : `工具授权已切换为${permissionModeName(next)}`)
      onUpdated?.(payload.workspace || payload)
    } catch (error) {
      setMode(previous)
      messageApi?.error(readableError(error))
    } finally {
      setSaving(false)
    }
  }

  return (
    <Tooltip title={permissionModeHint(mode)} placement="top">
      <Select
        size="small"
        className="sidebar-permission-mode"
        value={mode}
        onChange={change}
        options={options}
        disabled={!canWrite || saving || !workspace?.id}
        loading={saving}
        aria-label="工具授权档位"
      />
    </Tooltip>
  )
}
