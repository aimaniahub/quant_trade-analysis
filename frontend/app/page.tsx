'use client';

import dynamic from 'next/dynamic';

const Dashboard = dynamic(() => import('../components/Dashboard'), {
  ssr: false,
  loading: () => (
    <div className="w-screen h-screen flex items-center justify-center bg-[#07090d] text-zinc-400 font-mono text-xs">
      Loading Quant Intelligence Terminal...
    </div>
  ),
});

export default function Home() {
  return <Dashboard />;
}
