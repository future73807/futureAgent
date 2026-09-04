import React from 'react'
import Button from 'antd/es/button'
import Result from 'antd/es/result'

// 组件级错误边界：局部渲染崩溃不再导致整页白屏，可一键恢复。
export default class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props)
    this.state = { error: null, resetKey: 0 }
  }

  static getDerivedStateFromError(error) {
    return { error }
  }

  componentDidCatch(error) {
    // 与 index.html 的运行时错误留痕共用同一入口，便于诊断
    window.__runtimeErrors?.push('boundary: ' + String(error?.message || error))
  }

  render() {
    if (this.state.error) {
      return (
        <div style={{ maxWidth: 560, margin: '80px auto', padding: '0 16px' }}>
          <Result
            status="warning"
            title="页面区块渲染出错"
            subTitle={String(this.state.error?.message || this.state.error).slice(0, 200)}
            extra={[
              <Button key="retry" type="primary" onClick={() => this.setState((prev) => ({ error: null, resetKey: prev.resetKey + 1 }))}>
                重试渲染
              </Button>,
              <Button key="reload" onClick={() => window.location.reload()}>刷新页面</Button>,
            ]}
          />
        </div>
      )
    }
    return React.cloneElement(this.props.children, { key: `${this.props.resetToken ?? ''}-${this.state.resetKey}` })
  }
}
