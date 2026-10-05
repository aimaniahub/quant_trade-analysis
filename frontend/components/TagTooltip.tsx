'use client';

import React from 'react';

interface TagTooltipProps {
    tag: string;
    tooltip: string;
    className?: string;
    children?: React.ReactNode;
}

export default function TagTooltip({ tag, tooltip, className = '', children }: TagTooltipProps) {
    return (
        <span
            title={tooltip}
            className={`cursor-help inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-wider transition-colors hover:brightness-125 ${className}`}
        >
            {children || tag}
        </span>
    );
}
