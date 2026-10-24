import type { CSSProperties, ReactNode } from "react";

export type IconName = "monitor" | "shield" | "network" | "usage" | "search" | "arrow" | "chevron" | "download" | "pause" | "play" | "close" | "refresh" | "activity" | "check";
const paths: Record<IconName, ReactNode> = {
  monitor: <><rect x="3" y="4" width="18" height="13" rx="2" /><path d="M8 21h8M12 17v4m-6-9h3l2-4 3 7 2-3h2" /></>,
  shield: <><path d="M12 3 4 6v6c0 5 8 9 8 9s8-4 8-9V6l-8-3Z" /><path d="m9 12 2 2 4-5" /></>,
  network: <><rect x="9" y="2" width="6" height="6" rx="1" /><rect x="2" y="16" width="6" height="6" rx="1" /><rect x="16" y="16" width="6" height="6" rx="1" /><path d="M12 8v4H5v4m7-4h7v4" /></>,
  search: <><circle cx="10.5" cy="10.5" r="6.5" /><path d="m16 16 5 5" /></>,
  arrow: <path d="M4 12h16m-6-6 6 6-6 6" />,
  chevron: <path d="m9 5 7 7-7 7" />,
  download: <><path d="M12 3v12m-5-5 5 5 5-5M4 16v5h16v-5" /></>,
  pause: <path d="M8 4v16M16 4v16" />,
  play: <path d="m7 3 14 9-14 9V3Z" />,
  close: <path d="m6 6 12 12M6 18 18 6" />,
  refresh: <><path d="M20 7v5h-5M4 17v-5h5" /><path d="M6 7a7 7 0 0 1 12-1l2 3M4 15l2 3a7 7 0 0 0 12-1" /></>,
  activity: <path d="M2 12h5l3-8 4 16 3-8h5" />,
  usage: <><path d="M4 3v18h17M8 16v-5M13 16V6M18 16v-8" /></>,
  check: <path d="m5 12 4 4L19 6" />,
};
export default function Icon({ name, size = 18, style }: { name: IconName; size?: number; style?: CSSProperties }) {
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" style={style}>{paths[name]}</svg>;
}
