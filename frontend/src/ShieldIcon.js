import React from "react";

let shieldIdCounter = 0;

export default function ShieldIcon({ size = 64, className = "" }) {
  const [id] = React.useState(() => `shield-${shieldIdCounter++}`);

  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 64 64"
      width={size}
      height={size}
      className={className}
    >
      <defs>
        <clipPath id={`${id}-left`}>
          <rect x="0" y="0" width="32" height="64" />
        </clipPath>
        <clipPath id={`${id}-right`}>
          <rect x="32" y="0" width="32" height="64" />
        </clipPath>
        <linearGradient id={`${id}-grad`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#3b82f6" />
          <stop offset="100%" stopColor="#1e40af" />
        </linearGradient>
      </defs>
      {/* Left half — blue */}
      <path
        d="M32 4 L56 16 V34 C56 48 44 58 32 62 C20 58 8 48 8 34 V16 Z"
        fill={`url(#${id}-grad)`}
        clipPath={`url(#${id}-left)`}
      />
      {/* Right half — white */}
      <path
        d="M32 4 L56 16 V34 C56 48 44 58 32 62 C20 58 8 48 8 34 V16 Z"
        fill="white"
        clipPath={`url(#${id}-right)`}
      />
      {/* Outline */}
      <path
        d="M32 4 L56 16 V34 C56 48 44 58 32 62 C20 58 8 48 8 34 V16 Z"
        fill="none"
        stroke="#60a5fa"
        strokeWidth="1.5"
      />
    </svg>
  );
}
