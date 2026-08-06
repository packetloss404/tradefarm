// Rivalry Week weekly podcast tab — 0.16.0. Lists the last 4
// weeks' composed podcast episodes with a video player + a
// "view on YouTube" link when the YouTube video id is set.
//
// The data source is the per-week rollup the backend serves at
// /api/weekly/<week_id> (Dev B's recap scene endpoint). The
// rollup's `podcast` block carries the mp4 path, cover image,
// duration, file size, upload timestamp, and YouTube video id —
// all the fields the surface needs to render one card without
// a second round-trip.
//
// When the endpoint isn't reachable (older backends pre-0.16.0,
// the dev box without Dev B's recap scene yet) the SWR consumer
// falls back to an empty list and the tab renders a clear
// "no episodes yet" placeholder so the operator knows the
// feature is wired but the data path is missing.

import { useMemo } from "react";
import useSWR from "swr";
import { T } from "./tokens";
import { api } from "../api";
import type { WeeklyPodcast as WeeklyPodcastRow, WeeklyRollup } from "./types";

// ISO trading-week id for a Date. Mirrors the backend's
// `session.weekly_rollup.week_id_for` (Sunday-start trading week;
// Python isocalendar() is Monday-start so we shift by one day).
// The 1-day shift aligns Sunday + Monday into the same ISO week.
function weekIdFor(d: Date): string {
  const shifted = new Date(d);
  shifted.setUTCDate(shifted.getUTCDate() - 1);
  // isocalendar on UTC; mirror the backend's math.
  const isoYear = shifted.getUTCFullYear();
  // Find the Monday of the ISO week containing `shifted`.
  const dayOfWeek = shifted.getUTCDay() || 7; // 1..7, Mon=1
  const monday = new Date(shifted);
  monday.setUTCDate(shifted.getUTCDate() - (dayOfWeek - 1));
  // Compute the ISO week number for `monday`.
  const target = new Date(monday.valueOf());
  target.setUTCMonth(0, 1);
  const targetDay = target.getUTCDay() || 7;
  const weekNum =
    Math.ceil(((monday.valueOf() - target.valueOf()) / 86_400_000 + targetDay) / 7) || 1;
  return `${isoYear.toString().padStart(4, "0")}-W${weekNum.toString().padStart(2, "0")}`;
}

// Last N (default 4) week_ids ending at "this week" (the week
// containing `now`). Helper for the tab's data fetch — the
// caller doesn't need to know the current week_id.
function lastNWeekIds(now: Date, n: number): string[] {
  const ids: string[] = [];
  // Walk one week back at a time. `weekIdFor` only knows the
  // current date; subtract 7 days to get the previous week.
  for (let i = 0; i < n; i++) {
    const d = new Date(now);
    d.setUTCDate(d.getUTCDate() - i * 7);
    ids.push(weekIdFor(d));
  }
  return ids;
}

function formatDuration(sec: number): string {
  if (!sec || sec <= 0) return "—";
  const m = Math.floor(sec / 60);
  const s = sec % 60;
  return `${m}m ${s.toString().padStart(2, "0")}s`;
}

function formatSize(bytes: number): string {
  if (!bytes || bytes <= 0) return "—";
  if (bytes >= 1_000_000_000) return `${(bytes / 1_000_000_000).toFixed(2)} GB`;
  if (bytes >= 1_000_000) return `${(bytes / 1_000_000).toFixed(0)} MB`;
  if (bytes >= 1_000) return `${(bytes / 1_000).toFixed(0)} KB`;
  return `${bytes} B`;
}

function formatDateRange(dr?: [string, string]): string {
  if (!dr || dr.length !== 2) return "";
  return `${dr[0]} to ${dr[1]}`;
}

function EpisodeCard({
  weekId,
  rollup,
}: {
  weekId: string;
  rollup: WeeklyRollup | null | undefined;
}) {
  const podcast: WeeklyPodcastRow | null | undefined = rollup?.podcast;
  const mp4 = podcast?.path;
  const cover = podcast?.cover;
  const ytId = podcast?.youtube_video_id;
  const dateRange = formatDateRange(rollup?.date_range);
  return (
    <div
      style={{
        background: T.panel,
        border: `1px solid ${T.border}`,
        borderRadius: 6,
        padding: 16,
        display: "flex",
        flexDirection: "column",
        gap: 12,
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "baseline",
          justifyContent: "space-between",
          gap: 12,
        }}
      >
        <div style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
          <span
            style={{
              fontFamily: T.mono,
              fontSize: 11,
              letterSpacing: 1.5,
              color: T.text3,
            }}
          >
            WEEK
          </span>
          <span
            style={{
              fontFamily: T.mono,
              fontSize: 14,
              fontWeight: 600,
              color: T.text,
            }}
          >
            {weekId}
          </span>
          {dateRange && (
            <span
              style={{
                fontFamily: T.mono,
                fontSize: 11,
                color: T.text2,
              }}
            >
              · {dateRange}
            </span>
          )}
        </div>
        {ytId ? (
          <a
            href={`https://youtu.be/${ytId}`}
            target="_blank"
            rel="noreferrer"
            style={{
              fontFamily: T.mono,
              fontSize: 11,
              color: T.yt,
              textDecoration: "none",
              border: `1px solid ${T.yt}`,
              padding: "4px 8px",
              borderRadius: 4,
            }}
          >
            view on YouTube
          </a>
        ) : (
          <span
            style={{
              fontFamily: T.mono,
              fontSize: 11,
              color: T.text3,
              border: `1px solid ${T.border}`,
              padding: "4px 8px",
              borderRadius: 4,
            }}
          >
            not uploaded
          </span>
        )}
      </div>
      {mp4 ? (
        <video
          key={mp4}
          controls
          poster={cover || undefined}
          style={{
            width: "100%",
            maxHeight: 320,
            background: "#000",
            borderRadius: 4,
            border: `1px solid ${T.border}`,
          }}
          preload="metadata"
        >
          <source src={mp4} type="video/mp4" />
          {/* Empty caption track — the audio-only podcast has no
              on-screen captions, but the lint rule requires the
              element. Future: wire up the SRT from the script. */}
          <track kind="captions" />
          Your browser does not support embedded video.
        </video>
      ) : (
        <div
          style={{
            width: "100%",
            minHeight: 120,
            background: T.panel2,
            border: `1px solid ${T.border}`,
            borderRadius: 4,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            fontFamily: T.mono,
            fontSize: 12,
            color: T.text3,
          }}
        >
          {rollup
            ? "no podcast episode composed for this week"
            : "loading weekly rollup..."}
        </div>
      )}
      <div
        style={{
          display: "flex",
          gap: 18,
          fontFamily: T.mono,
          fontSize: 11,
          color: T.text2,
        }}
      >
        <span>duration: {formatDuration(podcast?.duration_sec ?? 0)}</span>
        <span style={{ color: T.text3 }}>·</span>
        <span>size: {formatSize(podcast?.size_bytes ?? 0)}</span>
        {podcast?.uploaded_at && (
          <>
            <span style={{ color: T.text3 }}>·</span>
            <span>uploaded: {podcast.uploaded_at.slice(0, 10)}</span>
          </>
        )}
      </div>
    </div>
  );
}

function useWeeklyRollup(weekId: string) {
  // The backend endpoint may not exist on pre-0.16.0 backends.
  // SWR returns `error` on non-2xx; the consumer treats that as
  // "no data" rather than a hard fail so the surface still
  // renders the placeholder.
  return useSWR<WeeklyRollup | null>(
    `/api/weekly/${weekId}`,
    async () => {
      try {
        return (await api.getWeeklyRollup(weekId)) as WeeklyRollup;
      } catch {
        return null;
      }
    },
    {
      revalidateOnFocus: false,
      shouldRetryOnError: false,
      dedupingInterval: 30_000,
    },
  );
}

function WeekRow({ weekId }: { weekId: string }) {
  const { data } = useWeeklyRollup(weekId);
  return <EpisodeCard weekId={weekId} rollup={data ?? null} />;
}

export function WeeklyPodcastTab() {
  // Compute the 4 most-recent week_ids once at mount. The 4-week
  // window matches the spec's "last 4 weeks" target.
  const weekIds = useMemo(() => lastNWeekIds(new Date(), 4), []);
  return (
    <div
      className="vod-no-scroll"
      style={{ padding: "20px 28px", flex: 1, overflow: "auto" }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "baseline",
          gap: 12,
          marginBottom: 4,
        }}
      >
        <span
          style={{
            fontFamily: T.mono,
            fontSize: 11,
            letterSpacing: 2,
            color: T.text3,
          }}
        >
          RIVALRY WEEK
        </span>
        <span
          style={{
            fontFamily: T.mono,
            fontSize: 11,
            color: T.text2,
          }}
        >
          30-min audio · last {weekIds.length} weeks
        </span>
      </div>
      <div
        style={{
          fontFamily: T.font,
          fontSize: 18,
          fontWeight: 600,
          color: T.text,
          marginBottom: 16,
        }}
      >
        Weekly podcast
      </div>
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "1fr 1fr",
          gap: 16,
        }}
      >
        {weekIds.map((wid) => (
          <WeekRow key={wid} weekId={wid} />
        ))}
      </div>
    </div>
  );
}
