import type { NextConfig } from "next";
import fs from "fs";
import path from "path";

// 嘗試讀取根目錄的 config.ini 取得 max_upload_size_mb
let maxUploadSize = "2048mb";
try {
  const configPath = path.resolve(process.cwd(), "../config.ini");
  if (fs.existsSync(configPath)) {
    const configContent = fs.readFileSync(configPath, "utf-8");
    const match = configContent.match(/max_upload_size_mb\s*=\s*(\d+)/);
    if (match && match[1]) {
      maxUploadSize = `${match[1]}mb`;
    }
  }
} catch (e) {
  console.warn("Failed to read config.ini for max_upload_size_mb, using default 2048mb");
}

const nextConfig: NextConfig = {
  experimental: {
    serverActions: {
      bodySizeLimit: maxUploadSize
    },
    proxyClientMaxBodySize: maxUploadSize
  } as any,
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: "http://127.0.0.1:8787/api/:path*",
      },
    ];
  },
};

export default nextConfig;
