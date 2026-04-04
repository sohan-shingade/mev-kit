interface Props {
  dexPrice: number | null;
  cexPrice: number | null;
}

export default function LivePrices({ dexPrice, cexPrice }: Props) {
  const spread =
    dexPrice && cexPrice
      ? (Math.abs(cexPrice - dexPrice) / cexPrice) * 10000
      : null;

  return (
    <div className="bg-bg-panel p-2">
      <div className="text-[10px] text-text-secondary uppercase tracking-wider mb-2">
        Live Prices
      </div>
      <div className="space-y-1.5">
        <div className="flex justify-between">
          <span className="text-xs text-text-secondary">DEX (Raydium)</span>
          <span className="font-mono text-sm font-semibold">
            {dexPrice?.toFixed(2) ?? "—"}
          </span>
        </div>
        <div className="flex justify-between">
          <span className="text-xs text-text-secondary">CEX (Binance)</span>
          <span className="font-mono text-sm font-semibold">
            {cexPrice?.toFixed(2) ?? "—"}
          </span>
        </div>
        <div className="flex justify-between border-t border-border pt-1.5">
          <span className="text-xs text-text-secondary">Spread</span>
          <span className="font-mono text-sm font-bold text-accent-amber">
            {spread ? `${spread.toFixed(1)} bps` : "—"}
          </span>
        </div>
      </div>
    </div>
  );
}
