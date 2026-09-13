import React, { useEffect, useState } from 'react'
import Button from 'antd/es/button'
import Dropdown from 'antd/es/dropdown'
import Flex from 'antd/es/flex'
import Tooltip from 'antd/es/tooltip'
import Typography from 'antd/es/typography'
import { DownOutlined, SafetyCertificateOutlined } from '@ant-design/icons'
import { apiFetch } from '../api.js'
import { useComposerDropdown } from '../composer-dropdown.jsx'
import { permissionModeHint, permissionModeName, permissionModes } from '../ui-labels.js'

const { Text } = Typography

function readableError(error) {
  return error?.detail || error?.message || '请求失败，请检查网络或稍后重试。'
}

/**
 * 授权档位 chip。
 *
 * 档位影响每一次执行要不要人工确认，属于高频开关；原先它埋在工作区设置页，
 * 用户执行前想改一次要跳三个页面。现在常驻在输入卡的动作行里（与参考稿的
 * 「完全访问」同位），与设置页共享同一份 workspace.permission_mode，
 * 两处改动都会即时反映到对方。
 */
export default function PermissionModeChip({ workspace, canWrite = true, onUpdated, messageApi, icon }) {
  const [mode, setMode] = useState(workspace?.permission_mode || 'default')
  const [saving, setSaving] = useState(false)
  // 与同排的其他 chip 共用"只开一个"的槽位，避免两个下拉叠在一起。
  const [open, setOpen] = useComposerDropdown('permission')

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

  const items = permissionModes.map((value) => ({
    key: value,
    label: (
      <Flex vertical style={{ minWidth: 0 }}>
        <Text strong={value === mode}>{permissionModeName(value)}</Text>
        <Text type="secondary" style={{ fontSize: 11, maxWidth: 280, whiteSpace: 'normal' }}>{permissionModeHint(value)}</Text>
      </Flex>
    ),
  }))

  return (
    <Tooltip title={permissionModeHint(mode)} placement="top">
      <Dropdown
        trigger={['click']}
        open={open}
        onOpenChange={setOpen}
        disabled={!canWrite || saving || !workspace?.id}
        menu={{ items, selectable: true, selectedKeys: [mode], onClick: ({ key }) => { change(key); setOpen(false) } }}
      >
        <Button
          type="text"
          size="small"
          className={`composer-chip${mode === 'full_access' ? ' composer-chip-warn' : ''}`}
          disabled={!canWrite || saving || !workspace?.id}
          loading={saving}
          aria-label="工具授权档位"
        >
          <Flex gap={5} align="center">
            {icon || <SafetyCertificateOutlined />}
            <span className="composer-chip-label">{permissionModeName(mode)}</span>
            <DownOutlined className="composer-chip-caret" />
          </Flex>
        </Button>
      </Dropdown>
    </Tooltip>
  )
}
