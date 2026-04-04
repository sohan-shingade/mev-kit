import { useEffect, useState } from "react";
import { get } from "../api/client";
import type { Guide } from "../api/types";
import { ExternalLink, BookOpen, ChevronRight } from "lucide-react";

interface GuideContent {
  slug: string;
  title: string;
  html: string;
}

interface ResourceLink {
  label: string;
  url: string;
  description: string;
}

interface ResourceCategory {
  title: string;
  links: ResourceLink[];
}

const EXTERNAL_RESOURCES: ResourceCategory[] = [
  {
    title: "Solana Core",
    links: [
      {
        label: "Solana Docs",
        url: "https://docs.solana.com",
        description: "Official Solana developer documentation",
      },
      {
        label: "Solana Cookbook",
        url: "https://solanacookbook.com",
        description: "Practical Solana development examples",
      },
      {
        label: "Solana Program Library",
        url: "https://spl.solana.com",
        description: "Token, stake, governance programs",
      },
    ],
  },
  {
    title: "MEV & Block Building",
    links: [
      {
        label: "Jito Docs",
        url: "https://docs.jito.wtf",
        description: "Jito block engine, bundles, and tips",
      },
      {
        label: "Jito MEV Overview",
        url: "https://www.jito.wtf/blog/the-state-of-mev-on-solana",
        description: "State of MEV on Solana",
      },
      {
        label: "Flashbots MEV Wiki",
        url: "https://ethereum.org/en/developers/docs/mev",
        description: "MEV fundamentals (Ethereum-focused but broadly applicable)",
      },
    ],
  },
  {
    title: "DEX Protocols",
    links: [
      {
        label: "Raydium SDK",
        url: "https://github.com/raydium-io/raydium-sdk-V2",
        description: "Official Raydium SDK for pool interactions",
      },
      {
        label: "Jupiter API Docs",
        url: "https://dev.jup.ag",
        description: "Jupiter swap aggregator and price API",
      },
      {
        label: "Orca SDK",
        url: "https://github.com/orca-so/whirlpools",
        description: "Orca Whirlpools concentrated liquidity",
      },
    ],
  },
  {
    title: "Data & RPC",
    links: [
      {
        label: "Helius Docs",
        url: "https://docs.helius.dev",
        description: "Enhanced RPC, webhooks, and DAS API",
      },
      {
        label: "Geyser Plugin Interface",
        url: "https://docs.solana.com/developing/plugins/geyser-plugins",
        description: "Real-time account and transaction streaming",
      },
      {
        label: "Yellowstone gRPC",
        url: "https://github.com/rpcpool/yellowstone-grpc",
        description: "High-performance Solana gRPC streaming",
      },
      {
        label: "Binance WS Streams",
        url: "https://developers.binance.com/docs/binance-spot-api-docs/web-socket-streams",
        description: "CEX price feeds via WebSocket",
      },
    ],
  },
  {
    title: "Python Libraries",
    links: [
      {
        label: "solders",
        url: "https://kevinheavey.github.io/solders",
        description: "Rust-backed Python library for Solana types",
      },
      {
        label: "solana-py",
        url: "https://michaelhly.github.io/solana-py",
        description: "Python client for Solana JSON RPC",
      },
      {
        label: "Pydantic v2",
        url: "https://docs.pydantic.dev/latest",
        description: "Data validation used for all mev-kit models",
      },
    ],
  },
];

export default function Learn() {
  const [guides, setGuides] = useState<Guide[]>([]);
  const [selectedSlug, setSelectedSlug] = useState<string | null>(null);
  const [content, setContent] = useState<GuideContent | null>(null);
  const [loadingGuides, setLoadingGuides] = useState(true);
  const [loadingContent, setLoadingContent] = useState(false);

  useEffect(() => {
    get<Guide[]>("/api/docs/guides")
      .then((g) => {
        setGuides(g);
        if (g.length > 0) setSelectedSlug(g[0].slug);
      })
      .catch(() => {})
      .finally(() => setLoadingGuides(false));
  }, []);

  useEffect(() => {
    if (!selectedSlug) return;
    setLoadingContent(true);
    setContent(null);
    get<GuideContent>(`/api/docs/guides/${selectedSlug}`)
      .then(setContent)
      .catch(() => {})
      .finally(() => setLoadingContent(false));
  }, [selectedSlug]);

  return (
    <div className="flex h-full min-h-0">
      {/* Sidebar */}
      <div className="w-52 shrink-0 bg-bg-sidebar border-r border-border flex flex-col overflow-y-auto">
        <div className="px-3 py-2 border-b border-border">
          <span className="text-[10px] text-text-secondary uppercase tracking-wider font-semibold">
            Guides
          </span>
        </div>
        {loadingGuides ? (
          <div className="px-3 py-4 text-xs text-text-secondary">Loading…</div>
        ) : guides.length === 0 ? (
          <div className="px-3 py-4 text-xs text-text-secondary italic">
            No guides available
          </div>
        ) : (
          <ul className="flex flex-col py-1">
            {guides.map((g) => (
              <li key={g.slug}>
                <button
                  onClick={() => setSelectedSlug(g.slug)}
                  className={`w-full text-left flex items-center gap-1.5 px-3 py-2 text-xs transition-colors ${
                    selectedSlug === g.slug
                      ? "bg-bg-active text-text-primary"
                      : "text-text-secondary hover:bg-bg-active/50 hover:text-text-primary"
                  }`}
                >
                  <BookOpen size={11} className="shrink-0" />
                  <span className="truncate">{g.title}</span>
                  {selectedSlug === g.slug && (
                    <ChevronRight size={10} className="ml-auto shrink-0" />
                  )}
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      {/* Content area */}
      <div className="flex-1 overflow-y-auto bg-bg-main">
        <div className="max-w-3xl mx-auto px-6 py-6">
          {loadingContent ? (
            <div className="py-12 text-center text-sm text-text-secondary">Loading…</div>
          ) : content ? (
            <>
              <h1 className="text-lg font-semibold text-text-primary mb-4">
                {content.title}
              </h1>
              <div
                className="prose-content"
                dangerouslySetInnerHTML={{ __html: content.html }}
                style={{
                  color: "var(--color-text-primary)",
                  fontSize: "0.8125rem",
                  lineHeight: "1.6",
                }}
              />
            </>
          ) : selectedSlug ? (
            <div className="py-12 text-center text-sm text-text-secondary">
              Failed to load guide
            </div>
          ) : (
            <div className="py-12 text-center text-sm text-text-secondary">
              Select a guide from the sidebar
            </div>
          )}

          {/* External resources section */}
          <div className="mt-10 pt-6 border-t border-border">
            <h2 className="text-sm font-semibold text-text-secondary uppercase tracking-wider mb-4">
              External Resources
            </h2>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {EXTERNAL_RESOURCES.map((cat) => (
                <div key={cat.title} className="flex flex-col gap-2">
                  <h3 className="text-[10px] text-accent-indigo uppercase tracking-wider font-semibold">
                    {cat.title}
                  </h3>
                  <ul className="flex flex-col gap-1.5">
                    {cat.links.map((link) => (
                      <li key={link.url}>
                        <a
                          href={link.url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="group flex items-start gap-2 hover:text-accent-indigo transition-colors"
                        >
                          <ExternalLink
                            size={11}
                            className="mt-0.5 shrink-0 text-text-secondary group-hover:text-accent-indigo"
                          />
                          <span className="flex flex-col gap-0.5">
                            <span className="text-xs text-text-primary group-hover:text-accent-indigo">
                              {link.label}
                            </span>
                            <span className="text-[10px] text-text-secondary">
                              {link.description}
                            </span>
                          </span>
                        </a>
                      </li>
                    ))}
                  </ul>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
