import path from "path";
import { fileURLToPath } from "url";

/** @type {import('next').NextConfig} */
const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const nextConfig = {
  // output: "export",  // 关闭静态导出以支持 rewrites
  compiler: {
    removeConsole: process.env.NODE_ENV === "production" ? { exclude: ["error", "warn"] } : false,
  },
  images: {
    unoptimized: true,
  },
  basePath: "",
  assetPrefix: "/litellm-asset-prefix",
  trailingSlash: true,
  turbopack: {
    root: __dirname,
  },
  // 重写所有 API 请求到 LiteLLM 代理 (解决跨域死循环)
  async rewrites() {
    return [
      {
        source: "/v1/:path*",
        destination: "http://localhost:4000/v1/:path*",
      },
      {
        source: "/config/:path*",
        destination: "http://localhost:4000/config/:path*",
      },
      {
        source: "/sso/:path*",
        destination: "http://localhost:4000/sso/:path*",
      },
      {
        source: "/login",
        destination: "http://localhost:4000/login",
      },
      {
        source: "/ui/:path*",
        destination: "http://localhost:4000/ui/:path*",
      },
      {
        source: "/key/:path*",
        destination: "http://localhost:4000/key/:path*",
      },
      {
        source: "/user/:path*",
        destination: "http://localhost:4000/user/:path*",
      },
      {
        source: "/team/:path*",
        destination: "http://localhost:4000/team/:path*",
      },
      {
        source: "/organization/:path*",
        destination: "http://localhost:4000/organization/:path*",
      },
      {
        source: "/spend/:path*",
        destination: "http://localhost:4000/spend/:path*",
      },
      {
        source: "/global/:path*",
        destination: "http://localhost:4000/global/:path*",
      },
      {
        source: "/model/:path*",
        destination: "http://localhost:4000/model/:path*",
      },
      {
        source: "/health",
        destination: "http://localhost:4000/health",
      },
      {
        source: "/public/:path*",
        destination: "http://localhost:4000/public/:path*",
      },
      {
        source: "/get/:path*",
        destination: "http://localhost:4000/get/:path*",
      },
      {
        source: "/litellm/:path*",
        destination: "http://localhost:4000/litellm/:path*",
      },
      {
        source: "/fallback/:path*",
        destination: "http://localhost:4000/fallback/:path*",
      },
    ];
  },
};

export default nextConfig;
