import React, { useState } from 'react'
import { Card, Typography, Empty } from 'antd'
import { SafetyOutlined } from '@ant-design/icons'

const { Title, Paragraph } = Typography

export default function AuthManager() {
  return (
    <div>
      <Title level={3} style={{ color: '#e0e0e0', marginBottom: 8 }}>
        权限管理
      </Title>
      <Paragraph style={{ color: '#888', marginBottom: 24 }}>
        管理用户角色和访问权限
      </Paragraph>
      <Card
        style={{
          background: '#1a1a2e',
          border: '1px solid #2a2a4a',
          borderRadius: 12,
        }}
      >
        <Empty
          image={<SafetyOutlined style={{ fontSize: 48, color: '#2a2a4a' }} />}
          description={
            <span style={{ color: '#888' }}>
              权限管理功能即将上线
            </span>
          }
        />
      </Card>
    </div>
  )
}
