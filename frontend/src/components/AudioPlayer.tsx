import React, { useEffect, useState } from "react";
import {
  voiceManager,
  buildCourtroomDeliberation,
  type DeliberationItem,
  type PlaybackState,
} from "../lib/voiceEngine";
import { AgentMark } from "./marks";
import type { TrialState } from "../useCase";

export function SpeakButton({
  item,
  className = "",
  size = "sm",
}: {
  item: DeliberationItem;
  className?: string;
  size?: "sm" | "xs";
}) {
  const [state, setState] = useState<PlaybackState>(voiceManager.getState());

  useEffect(() => {
    return voiceManager.subscribe(setState);
  }, []);

  if (!state.isSupported) return null;

  const isThisPlaying =
    state.isPlaying &&
    !state.isPaused &&
    state.currentItem?.id === item.id;

  const handleClick = (e: React.MouseEvent) => {
    e.stopPropagation();
    if (isThisPlaying) {
      voiceManager.pause();
    } else if (state.currentItem?.id === item.id && state.isPaused) {
      voiceManager.resume();
    } else {
      voiceManager.playSingleItem(item);
    }
  };

  const btnSize = size === "xs" ? "px-1.5 py-0.5 text-[11px]" : "px-2 py-1 text-xs";

  return (
    <button
      type="button"
      onClick={handleClick}
      title={isThisPlaying ? "Pause voice" : `Listen to ${item.title}`}
      aria-label={`Listen to ${item.title}`}
      className={`inline-flex items-center gap-1.5 rounded border transition-colors ${
        isThisPlaying
          ? "border-accent bg-accent text-sheet"
          : "border-rule-2 bg-sheet text-ink-2 hover:border-ink hover:text-ink"
      } ${btnSize} ${className}`}
    >
      {isThisPlaying ? (
        <>
          <span className="flex h-2.5 items-end gap-0.5" aria-hidden="true">
            <span className="w-0.5 animate-[pulse_0.6s_ease-in-out_infinite] bg-sheet h-2" />
            <span className="w-0.5 animate-[pulse_0.4s_ease-in-out_infinite] bg-sheet h-3" />
            <span className="w-0.5 animate-[pulse_0.5s_ease-in-out_infinite] bg-sheet h-1.5" />
          </span>
          <span className="font-medium">Playing</span>
        </>
      ) : (
        <>
          <span className="text-[12px]" aria-hidden="true">🔊</span>
          <span>Listen</span>
        </>
      )}
    </button>
  );
}

/**
 * Courtroom Deliberation Bar
 * Sits at the top/bottom of the Trial & Briefing views, providing full playback controls,
 * current speaker transcript, progress, and speed adjustments.
 */
export function CourtroomAudioBar({
  trial,
  question,
  caseFile,
}: {
  trial: TrialState;
  question?: string;
  caseFile?: any;
}) {
  const [state, setState] = useState<PlaybackState>(voiceManager.getState());
  const [minimized, setMinimized] = useState(false);
  const [playlist, setPlaylist] = useState<DeliberationItem[]>([]);

  useEffect(() => {
    return voiceManager.subscribe(setState);
  }, []);

  useEffect(() => {
    const items = buildCourtroomDeliberation(trial, question, caseFile);
    setPlaylist(items);
  }, [trial, question, caseFile]);

  if (!state.isSupported || !playlist.length) return null;

  const currentItem = state.currentItem;
  const progressPercent =
    state.totalItems > 0 && state.currentIndex >= 0
      ? Math.round(((state.currentIndex + 1) / state.totalItems) * 100)
      : 0;

  const handleStartFullTrial = () => {
    if (state.isPlaying) {
      voiceManager.stop();
    } else {
      voiceManager.playDeliberation(playlist, 0);
    }
  };

  const handleTogglePlay = () => {
    if (!state.isPlaying) {
      voiceManager.playDeliberation(playlist, 0);
    } else if (state.isPaused) {
      voiceManager.resume();
    } else {
      voiceManager.pause();
    }
  };

  const speeds = [0.85, 1.0, 1.25, 1.5];

  return (
    <section
      aria-label="Courtroom Audio Deliberation"
      className="mb-5 overflow-hidden rounded-md border border-rule-2 bg-sheet shadow-xs"
    >
      {/* Header Bar */}
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-rule bg-paper px-3.5 py-2">
        <div className="flex items-center gap-2">
          <span className="text-base" aria-hidden="true">🎙️</span>
          <span className="font-semibold text-ink text-[13px] tracking-tight">
            Courtroom Audio Deliberation
          </span>
          <span className="rounded bg-accent-wash px-2 py-0.5 text-[11px] font-medium text-accent">
            Voice Synthesis ({playlist.length} parts)
          </span>
        </div>

        <div className="flex items-center gap-2">
          {!state.isPlaying && (
            <button
              type="button"
              onClick={handleStartFullTrial}
              className="inline-flex items-center gap-1.5 rounded bg-ink px-3 py-1 text-xs font-medium text-sheet hover:bg-ink/90 transition-colors"
            >
              <span>▶</span> Play Trial Deliberation
            </button>
          )}

          {state.isPlaying && (
            <button
              type="button"
              onClick={() => setMinimized((m) => !m)}
              className="text-xs text-ink-3 hover:text-ink px-1.5 py-0.5"
              title={minimized ? "Expand audio console" : "Minimize audio console"}
            >
              {minimized ? "Expand ▲" : "Collapse ▼"}
            </button>
          )}
        </div>
      </div>

      {/* Main Console */}
      {!minimized && (
        <div className="p-3.5">
          {state.isPlaying && currentItem ? (
            <div className="space-y-3">
              {/* Speaker & Action Header */}
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="flex items-center gap-2.5">
                  <AgentMark agent={currentItem.agent} />
                  <span className="text-xs font-medium text-ink-2">
                    {currentItem.title}
                  </span>
                  {currentItem.badge && (
                    <span className="rounded border border-rule px-1.5 py-0.5 text-[10px] font-mono uppercase text-ink-3">
                      {currentItem.badge}
                    </span>
                  )}
                </div>

                <div className="text-xs font-mono text-ink-3">
                  Part {state.currentIndex + 1} of {state.totalItems}
                </div>
              </div>

              {/* Spoken Text Display */}
              <div className="rounded border border-accent-line/50 bg-accent-wash/30 p-2.5 transition-colors">
                <p className="m-0 text-[13px] leading-relaxed text-ink font-sans">
                  "{currentItem.displayText}"
                </p>
              </div>

              {/* Progress Scrub Bar */}
              <div className="space-y-1">
                <div className="h-1.5 w-full overflow-hidden rounded-full bg-paper">
                  <div
                    className="h-full bg-accent transition-all duration-300"
                    style={{ width: `${progressPercent}%` }}
                  />
                </div>
              </div>

              {/* Player Controls & Speed Selector */}
              <div className="flex flex-wrap items-center justify-between gap-3 pt-1">
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={() => voiceManager.previous()}
                    disabled={state.currentIndex <= 0}
                    title="Previous act"
                    className="rounded border border-rule-2 px-2 py-1 text-xs hover:bg-paper disabled:opacity-40"
                  >
                    ⏮ Prev
                  </button>

                  <button
                    type="button"
                    onClick={handleTogglePlay}
                    className="rounded border border-ink bg-ink px-3 py-1 text-xs font-medium text-sheet hover:bg-ink/90"
                  >
                    {state.isPaused ? "▶ Resume" : "⏸ Pause"}
                  </button>

                  <button
                    type="button"
                    onClick={() => voiceManager.next()}
                    disabled={state.currentIndex >= state.totalItems - 1}
                    title="Next act"
                    className="rounded border border-rule-2 px-2 py-1 text-xs hover:bg-paper disabled:opacity-40"
                  >
                    Next ⏭
                  </button>

                  <button
                    type="button"
                    onClick={() => voiceManager.stop()}
                    title="Stop playback"
                    className="rounded border border-rule-2 px-2 py-1 text-xs text-bad hover:bg-bad-wash"
                  >
                    ⏹ Stop
                  </button>
                </div>

                {/* Speed Multiplier */}
                <div className="flex items-center gap-1.5 text-xs text-ink-2">
                  <span className="text-ink-3">Speed:</span>
                  {speeds.map((s) => (
                    <button
                      key={s}
                      type="button"
                      onClick={() => voiceManager.setSpeed(s)}
                      className={`rounded px-1.5 py-0.5 font-mono text-[11px] ${
                        state.speedMultiplier === s
                          ? "bg-ink font-semibold text-sheet"
                          : "border border-rule hover:bg-paper"
                      }`}
                    >
                      {s}x
                    </button>
                  ))}
                </div>
              </div>
            </div>
          ) : (
            /* Idle State */
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 text-xs text-ink-2">
              <div className="space-y-0.5">
                <p className="m-0 font-medium text-ink">
                  Hear the adversarial debate play out live.
                </p>
                <p className="m-0 text-ink-3">
                  Heimdall presents the case file, Thor and Loki debate exposure with distinct voices, and Odin delivers sovereign verdicts.
                </p>
              </div>

              <div className="flex items-center gap-2 shrink-0">
                <button
                  type="button"
                  onClick={handleStartFullTrial}
                  className="rounded border border-ink bg-ink px-3 py-1.5 font-medium text-sheet hover:bg-ink/90 transition-colors"
                >
                  ▶ Play Full Deliberation
                </button>
              </div>
            </div>
          )}
        </div>
      )}
    </section>
  );
}
