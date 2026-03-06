import React from "react";

export default function ShieldIcon({ size = 64, className = "" }) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 64 64"
      width={size}
      height={size}
      className={className}
    >
      <defs>
        <linearGradient id="shield-grad" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#3b82f6" />
          <stop offset="100%" stopColor="#1e40af" />
        </linearGradient>
      </defs>
      <path
        d="M32 4 L56 16 V34 C56 48 44 58 32 62 C20 58 8 48 8 34 V16 Z"
        fill="url(#shield-grad)"
        stroke="#60a5fa"
        strokeWidth="1.5"
      />
      <path
        d="M32 18 L24 30 H30 V42 H34 V30 H40 Z"
        fill="white"
        opacity="0.9"
      />
    </svg>
  );
}
