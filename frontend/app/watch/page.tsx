'use client';

import dynamic from 'next/dynamic';

const TradeWatch = dynamic(() => import('../../components/TradeWatch'), {
  ssr: false,
  loading: () => (
    <div className="w-screen h-screen flex items-center justify-center bg-[#07090d] text-zinc-400 font-mono text-xs">
      Loading TradeWatch...
    </div>
  ),
});

export default function WatchPage() {
  return <TradeWatch />;
}
