import React from 'react'
import { Card, Typography, Empty } from 'antd'
import { SettingOutlined } from '@ant-design/icons'

const { Title, Paragraph } = Typography

export default function SettingsPanel() {
  return (
    <div>
      <Title level={3} style={{ color: '#e0e0e0', marginBottom: 8 }}>
        设置
      </Title>
      <Paragraph style={{ color: '#888', marginBottom: 24 }}>
        系统配置
      </Paragraph>
      <Card
        style={{
          background: '#1a1a2e',
          border: '1px solid #2a2a4a',
          borderRadius: 12,
        }}
      >
        <Empty
          image={<SettingOutlined style={{ fontSize: 48, color: '#2a2a4a' }} />}
          description={
            <span style={{ color: '#888' }}>
              设置功能即将上线
            </span>
          }
        />
      </Card>
    </div>
  )
}
