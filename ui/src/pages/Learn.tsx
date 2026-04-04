import { useEffect, useState } from "react";
import { get } from "../api/client";
import type { Guide } from "../api/types";
import {
  ExternalLink,
  BookOpen,
  ChevronLeft,
  ChevronRight,
  Sparkles,
  Globe,
  Layers,
  Code2,
  FlaskConical,
} from "lucide-react";

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

const GUIDE_ICONS = [Sparkles, Globe, Layers, Code2, FlaskConical];

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
  const [showResources, setShowResources] = useState(false);

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
    setShowResources(false);
    get<GuideContent>(`/api/docs/guides/${selectedSlug}`)
      .then(setContent)
      .catch(() => {})
      .finally(() => setLoadingContent(false));
  }, [selectedSlug]);

  const currentIndex = guides.findIndex((g) => g.slug === selectedSlug);
  const prevGuide = currentIndex > 0 ? guides[currentIndex - 1] : null;
  const nextGuide =
    currentIndex >= 0 && currentIndex < guides.length - 1
      ? guides[currentIndex + 1]
      : null;

  return (
    <div className="flex h-full min-h-0">
      {/* ── Sidebar ── */}
      <div className="w-[220px] shrink-0 bg-bg-sidebar border-r border-border flex flex-col overflow-y-auto">
        {/* Logo area */}
        <div className="px-4 py-4 border-b border-border">
          <div className="flex items-center gap-2">
            <BookOpen size={14} className="text-accent-indigo" />
            <span className="text-xs font-semibold text-text-primary uppercase tracking-wider">
              Documentation
            </span>
          </div>
        </div>

        {/* Guide nav */}
        <div className="px-2 py-3">
          <div className="px-2 mb-2">
            <span className="text-[10px] text-text-secondary uppercase tracking-wider font-medium">
              Guides
            </span>
          </div>
          {loadingGuides ? (
            <div className="px-3 py-4 text-xs text-text-secondary">
              Loading...
            </div>
          ) : (
            <ul className="flex flex-col gap-0.5">
              {guides.map((g, i) => {
                const Icon = GUIDE_ICONS[i] ?? BookOpen;
                const active = selectedSlug === g.slug;
                return (
                  <li key={g.slug}>
                    <button
                      onClick={() => setSelectedSlug(g.slug)}
                      className={`w-full text-left flex items-center gap-2.5 px-3 py-2 rounded-md text-xs transition-colors ${
                        active
                          ? "bg-accent-indigo/20 text-accent-indigo border border-accent-indigo/50"
                          : "text-text-secondary hover:bg-bg-active/50 hover:text-text-primary border border-transparent"
                      }`}
                    >
                      <Icon size={13} className="shrink-0" />
                      <span className="truncate leading-snug">{g.title}</span>
                    </button>
                  </li>
                );
              })}
            </ul>
          )}

          {/* External resources nav item */}
          <div className="px-2 mt-4 mb-2">
            <span className="text-[10px] text-text-secondary uppercase tracking-wider font-medium">
              Reference
            </span>
          </div>
          <button
            onClick={() => {
              setSelectedSlug(null);
              setContent(null);
              setShowResources(true);
            }}
            className={`w-full text-left flex items-center gap-2.5 px-3 py-2 rounded-md text-xs transition-colors ${
              showResources
                ? "bg-accent-indigo/20 text-accent-indigo border border-accent-indigo/50"
                : "text-text-secondary hover:bg-bg-active/50 hover:text-text-primary border border-transparent"
            }`}
          >
            <ExternalLink size={13} className="shrink-0" />
            <span>External Resources</span>
          </button>
        </div>
      </div>

      {/* ── Content area ── */}
      <div className="flex-1 overflow-y-auto bg-bg-main">
        {loadingContent ? (
          <div className="max-w-3xl mx-auto px-8 py-16 text-center">
            <div className="inline-block w-5 h-5 border-2 border-accent-indigo border-t-transparent rounded-full animate-spin" />
            <p className="text-xs text-text-secondary mt-3">Loading guide...</p>
          </div>
        ) : content ? (
          <div className="max-w-3xl mx-auto px-8 py-8">
            {/* Breadcrumb */}
            <div className="flex items-center gap-1.5 text-[11px] text-text-secondary mb-6">
              <span>Docs</span>
              <ChevronRight size={10} />
              <span>Guides</span>
              <ChevronRight size={10} />
              <span className="text-text-primary">{content.title}</span>
            </div>

            {/* Rendered guide */}
            <div
              className="prose-content"
              dangerouslySetInnerHTML={{ __html: content.html }}
            />

            {/* Prev / Next navigation */}
            <div className="flex items-stretch gap-3 mt-10 pt-6 border-t border-border">
              {prevGuide ? (
                <button
                  onClick={() => setSelectedSlug(prevGuide.slug)}
                  className="flex-1 flex items-center gap-3 px-4 py-3 rounded-md border border-border bg-bg-panel/30 hover:bg-bg-panel/50 hover:border-accent-indigo/50 transition-colors text-left group"
                >
                  <ChevronLeft
                    size={16}
                    className="text-text-secondary group-hover:text-accent-indigo shrink-0"
                  />
                  <div>
                    <div className="text-[10px] text-text-secondary uppercase tracking-wider">
                      Previous
                    </div>
                    <div className="text-xs text-text-primary mt-0.5 group-hover:text-accent-indigo transition-colors">
                      {prevGuide.title}
                    </div>
                  </div>
                </button>
              ) : (
                <div className="flex-1" />
              )}
              {nextGuide ? (
                <button
                  onClick={() => setSelectedSlug(nextGuide.slug)}
                  className="flex-1 flex items-center justify-end gap-3 px-4 py-3 rounded-md border border-border bg-bg-panel/30 hover:bg-bg-panel/50 hover:border-accent-indigo/50 transition-colors text-right group"
                >
                  <div>
                    <div className="text-[10px] text-text-secondary uppercase tracking-wider">
                      Next
                    </div>
                    <div className="text-xs text-text-primary mt-0.5 group-hover:text-accent-indigo transition-colors">
                      {nextGuide.title}
                    </div>
                  </div>
                  <ChevronRight
                    size={16}
                    className="text-text-secondary group-hover:text-accent-indigo shrink-0"
                  />
                </button>
              ) : (
                <div className="flex-1" />
              )}
            </div>
          </div>
        ) : showResources ? (
          /* ── External Resources view ── */
          <div className="max-w-3xl mx-auto px-8 py-8">
            <div className="flex items-center gap-1.5 text-[11px] text-text-secondary mb-6">
              <span>Docs</span>
              <ChevronRight size={10} />
              <span className="text-text-primary">External Resources</span>
            </div>

            <h1 className="text-lg font-semibold text-text-primary mb-1">
              External Resources
            </h1>
            <p className="text-sm text-text-secondary mb-8">
              Curated links for the Solana MEV ecosystem — protocols, data
              sources, and developer tools.
            </p>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              {EXTERNAL_RESOURCES.map((cat) => (
                <div
                  key={cat.title}
                  className="border border-border rounded-md bg-bg-panel/30 overflow-hidden"
                >
                  <div className="px-4 py-2.5 border-b border-border bg-bg-panel/30">
                    <h3 className="text-[11px] text-accent-indigo uppercase tracking-wider font-semibold">
                      {cat.title}
                    </h3>
                  </div>
                  <ul className="divide-y divide-border/40">
                    {cat.links.map((link) => (
                      <li key={link.url}>
                        <a
                          href={link.url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="group flex items-start gap-3 px-4 py-3 hover:bg-bg-active/50 transition-colors"
                        >
                          <ExternalLink
                            size={12}
                            className="mt-0.5 shrink-0 text-text-secondary group-hover:text-accent-indigo transition-colors"
                          />
                          <div className="flex flex-col">
                            <span className="text-xs text-text-primary font-medium group-hover:text-accent-indigo transition-colors">
                              {link.label}
                            </span>
                            <span className="text-[11px] text-text-secondary mt-0.5 leading-snug">
                              {link.description}
                            </span>
                          </div>
                        </a>
                      </li>
                    ))}
                  </ul>
                </div>
              ))}
            </div>
          </div>
        ) : (
          <div className="max-w-3xl mx-auto px-8 py-16 text-center">
            <BookOpen size={32} className="mx-auto text-text-secondary mb-3" />
            <p className="text-sm text-text-secondary">
              Select a guide from the sidebar to get started
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
