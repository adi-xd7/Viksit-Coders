/**
 * Courtroom Audio Deliberation & Voice Synthesis Engine
 * Provides distinct personas (Heimdall, Thor, Loki, Odin, Court Herald)
 * using the native Web Speech API (zero external dependencies or costs).
 */

import type { TrialState } from "../useCase";
import { agentName } from "../components/marks";

export type AgentVoiceId = "heimdall" | "thor" | "loki" | "odin" | "court";

export interface VoiceProfile {
  id: AgentVoiceId;
  name: string;
  role: string;
  pitch: number;
  rate: number;
  voiceGenderPref: "male" | "female" | "deep" | "any";
}

export const AGENT_PROFILES: Record<AgentVoiceId, VoiceProfile> = {
  court: {
    id: "court",
    name: "Herald",
    role: "Court Officer",
    pitch: 1.0,
    rate: 1.05,
    voiceGenderPref: "any",
  },
  heimdall: {
    id: "heimdall",
    name: "Heimdall",
    role: "Intelligence Investigator",
    pitch: 1.02,
    rate: 1.0,
    voiceGenderPref: "male",
  },
  thor: {
    id: "thor",
    name: "Thor",
    role: "High Exposure Advocate",
    pitch: 0.82, // Deeper, powerful, emphatic
    rate: 0.95,
    voiceGenderPref: "deep",
  },
  loki: {
    id: "loki",
    name: "Loki",
    role: "Limited Exposure Advocate",
    pitch: 1.25, // Sharp, swift, skeptical
    rate: 1.12,
    voiceGenderPref: "male",
  },
  odin: {
    id: "odin",
    name: "Odin",
    role: "Chief Justice / All-Father",
    pitch: 0.72, // Sovereign, low resonance, solemn
    rate: 0.88,
    voiceGenderPref: "deep",
  },
};

export interface DeliberationItem {
  id: string;
  agent: AgentVoiceId;
  phase: "intro" | "case_file" | "claim" | "attack" | "defense" | "concession" | "ruling" | "conclusion";
  title: string;
  badge?: string;
  spokenText: string;
  displayText: string;
  targetClaimId?: string;
}

class VoiceSynthesisManager {
  private synth: SpeechSynthesis | null = null;
  private voices: SpeechSynthesisVoice[] = [];
  private speedMultiplier = 1.0;
  private volume = 1.0;
  
  // Queue state
  private playlist: DeliberationItem[] = [];
  private currentIndex = -1;
  private isPlaying = false;
  private isPaused = false;
  private listeners: Set<(state: PlaybackState) => void> = new Set();
  private keepAliveTimer: number | null = null;

  constructor() {
    if (typeof window !== "undefined" && "speechSynthesis" in window) {
      this.synth = window.speechSynthesis;
      this.loadVoices();
      if (this.synth.onvoiceschanged !== undefined) {
        this.synth.onvoiceschanged = () => this.loadVoices();
      }
    }
  }

  public isSupported(): boolean {
    return this.synth !== null;
  }

  private loadVoices() {
    if (!this.synth) return;
    this.voices = this.synth.getVoices();
  }

  private getBestVoiceForAgent(agent: AgentVoiceId): SpeechSynthesisVoice | null {
    if (!this.voices.length) this.loadVoices();
    if (!this.voices.length) return null;

    const englishVoices = this.voices.filter((v) => v.lang.startsWith("en"));
    const pool = englishVoices.length ? englishVoices : this.voices;

    const profile = AGENT_PROFILES[agent];

    if (profile.voiceGenderPref === "deep" || agent === "odin" || agent === "thor") {
      // Look for male, deep, or standard names
      const match = pool.find((v) => 
        /david|mark|guy|richard|george|male|en-us|en-gb/i.test(v.name) &&
        !/zira|female|hazel|susan|catherine/i.test(v.name)
      );
      if (match) return match;
    } else if (agent === "loki") {
      // Loki: look for UK English, distinct accent or articulate voice
      const ukMatch = pool.find((v) => /en-gb|uk|george|oliver/i.test(v.lang) || /en-gb|uk/i.test(v.name));
      if (ukMatch) return ukMatch;
    } else if (agent === "heimdall") {
      const formalMatch = pool.find((v) => /natural|en-us|google/i.test(v.name));
      if (formalMatch) return formalMatch;
    }

    return pool[0] ?? null;
  }

  public subscribe(callback: (state: PlaybackState) => void): () => void {
    this.listeners.add(callback);
    callback(this.getState());
    return () => this.listeners.delete(callback);
  }

  private notify() {
    const st = this.getState();
    this.listeners.forEach((cb) => cb(st));
  }

  public getState(): PlaybackState {
    const cur = this.currentIndex >= 0 && this.currentIndex < this.playlist.length 
      ? this.playlist[this.currentIndex] 
      : null;
    return {
      isSupported: this.isSupported(),
      isPlaying: this.isPlaying,
      isPaused: this.isPaused,
      currentIndex: this.currentIndex,
      totalItems: this.playlist.length,
      currentItem: cur,
      speedMultiplier: this.speedMultiplier,
      volume: this.volume,
    };
  }

  public setSpeed(speed: number) {
    this.speedMultiplier = Math.max(0.75, Math.min(2.0, speed));
    this.notify();
    // If currently speaking, restart current item with new speed
    if (this.isPlaying && !this.isPaused && this.currentIndex >= 0) {
      const idx = this.currentIndex;
      this.speakItem(idx);
    }
  }

  public setVolume(vol: number) {
    this.volume = Math.max(0, Math.min(1, vol));
    this.notify();
  }

  public playDeliberation(items: DeliberationItem[], startIndex = 0) {
    if (!this.synth || !items.length) return;
    this.stop();
    this.playlist = items;
    this.currentIndex = Math.max(0, Math.min(items.length - 1, startIndex));
    this.isPlaying = true;
    this.isPaused = false;
    this.speakItem(this.currentIndex);
  }

  public playSingleItem(item: DeliberationItem) {
    if (!this.synth) return;
    this.stop();
    this.playlist = [item];
    this.currentIndex = 0;
    this.isPlaying = true;
    this.isPaused = false;
    this.speakItem(0);
  }

  private speakItem(index: number) {
    if (!this.synth || index < 0 || index >= this.playlist.length) {
      this.stop();
      return;
    }

    this.currentIndex = index;
    const item = this.playlist[index];
    const profile = AGENT_PROFILES[item.agent];

    this.synth.cancel();

    // Clean text for speech (strip markdown characters, brackets, refs)
    const cleanSpeech = cleanTextForSpeech(item.spokenText);
    const utt = new SpeechSynthesisUtterance(cleanSpeech);

    const voice = this.getBestVoiceForAgent(item.agent);
    if (voice) utt.voice = voice;

    utt.pitch = profile.pitch;
    utt.rate = profile.rate * this.speedMultiplier;
    utt.volume = this.volume;

    utt.onstart = () => {
      this.isPlaying = true;
      this.isPaused = false;
      this.notify();
      this.startKeepAlive();
    };

    utt.onend = () => {
      this.stopKeepAlive();
      if (this.isPlaying && !this.isPaused) {
        if (this.currentIndex + 1 < this.playlist.length) {
          // Speak next item in sequence with natural courtroom pause
          setTimeout(() => {
            if (this.isPlaying && !this.isPaused) {
              this.speakItem(this.currentIndex + 1);
            }
          }, 350);
        } else {
          this.stop();
        }
      }
    };

    utt.onerror = (e) => {
      this.stopKeepAlive();
      if (e.error !== "canceled" && e.error !== "interrupted") {
        console.warn("Speech synthesis error:", e);
      }
      if (this.isPlaying && !this.isPaused && this.currentIndex + 1 < this.playlist.length) {
        this.speakItem(this.currentIndex + 1);
      } else {
        this.stop();
      }
    };

    this.synth.speak(utt);
    this.notify();
  }

  // Chrome workaround: long utterances pause after 15 seconds unless briefly resumed
  private startKeepAlive() {
    this.stopKeepAlive();
    this.keepAliveTimer = window.setInterval(() => {
      if (this.synth && this.isPlaying && !this.isPaused) {
        this.synth.pause();
        this.synth.resume();
      }
    }, 10000);
  }

  private stopKeepAlive() {
    if (this.keepAliveTimer !== null) {
      clearInterval(this.keepAliveTimer);
      this.keepAliveTimer = null;
    }
  }

  public pause() {
    if (!this.synth || !this.isPlaying || this.isPaused) return;
    this.synth.pause();
    this.isPaused = true;
    this.stopKeepAlive();
    this.notify();
  }

  public resume() {
    if (!this.synth || !this.isPlaying || !this.isPaused) return;
    this.synth.resume();
    this.isPaused = false;
    this.startKeepAlive();
    this.notify();
  }

  public next() {
    if (!this.playlist.length) return;
    if (this.currentIndex + 1 < this.playlist.length) {
      this.speakItem(this.currentIndex + 1);
    } else {
      this.stop();
    }
  }

  public previous() {
    if (!this.playlist.length) return;
    if (this.currentIndex > 0) {
      this.speakItem(this.currentIndex - 1);
    } else {
      this.speakItem(0);
    }
  }

  public stop() {
    this.stopKeepAlive();
    if (this.synth) {
      this.synth.cancel();
    }
    this.isPlaying = false;
    this.isPaused = false;
    this.currentIndex = -1;
    this.notify();
  }
}

export interface PlaybackState {
  isSupported: boolean;
  isPlaying: boolean;
  isPaused: boolean;
  currentIndex: number;
  totalItems: number;
  currentItem: DeliberationItem | null;
  speedMultiplier: number;
  volume: number;
}

export const voiceManager = new VoiceSynthesisManager();

/**
 * Strips markdown symbols, brackets, and table notation for clean phonetic delivery.
 */
function cleanTextForSpeech(text: string): string {
  return text
    .replace(/\[.*?\]/g, "") // remove bracketed citations like [ORV-0001 P2]
    .replace(/[#*_`~]/g, "") // remove markdown styling symbols
    .replace(/\s+/g, " ")
    .replace(/\b([A-Z]{2,4})-(\d{4})\b/g, "$1 $2") // ORV-0005 -> ORV 0005
    .trim();
}

/**
 * Assembles the full Courtroom Deliberation sequence from the Case State.
 */
export function buildCourtroomDeliberation(
  trial: TrialState,
  question?: string,
  caseFile?: any
): DeliberationItem[] {
  const items: DeliberationItem[] = [];
  const cf = trial.caseFile ?? caseFile;

  // 1. Court Opening
  items.push({
    id: "court-opening",
    agent: "court",
    phase: "intro",
    title: "Court Opening",
    badge: "Session Open",
    spokenText: `All rise. The Trial of the Nine Realms is now convened. ${
      question ? `The matter before the court: ${question}` : "Examining the supply chain disruption."
    }`,
    displayText: question ? `The matter before the court: ${question}` : "Opening session of the Ragnarok court.",
  });

  // 2. Heimdall's Case File Report
  if (cf) {
    const status = cf.event_status ?? "verified";
    const countries = (cf.countries ?? []).join(", ");
    const sectors = (cf.sectors ?? []).join(", ");
    const tablesCount = (cf.trade_table_ids ?? []).length;
    const docsCount = (cf.evidence_doc_ids ?? []).length;

    items.push({
      id: "heimdall-case-file",
      agent: "heimdall",
      phase: "case_file",
      title: "Heimdall · Case File Briefing",
      badge: `Event ${status}`,
      spokenText: `Heimdall reporting. Investigation into the disruption confirms the event is ${status}. Affected territories: ${
        countries || "Midgard and Tolan"
      }. Key commodity sectors: ${sectors || "wheat and maize"}. I have verified ${docsCount} intelligence documents and ${tablesCount} customs trade tables into the Case File.`,
      displayText: `Event verified as "${status}". ${docsCount} documents and ${tablesCount} trade tables lodged into the Case File.`,
    });
  }

  // 3. Thor's Opening Claims (High Exposure)
  const thorClaims = trial.claims.filter((c) => c.agent === "thor");
  for (const c of thorClaims) {
    items.push({
      id: `claim-${c.claim_id}`,
      agent: "thor",
      phase: "claim",
      title: `Thor · Claim ${c.claim_id}`,
      badge: "High Exposure",
      spokenText: `Thor speaking. Claim ${c.claim_id}. ${c.text}`,
      displayText: c.text,
      targetClaimId: c.claim_id,
    });
  }

  // 4. Loki's Opening Claims (Limited Exposure)
  const lokiClaims = trial.claims.filter((c) => c.agent === "loki");
  for (const c of lokiClaims) {
    items.push({
      id: `claim-${c.claim_id}`,
      agent: "loki",
      phase: "claim",
      title: `Loki · Claim ${c.claim_id}`,
      badge: "Limited Exposure",
      spokenText: `Loki speaking. Claim ${c.claim_id}. ${c.text}`,
      displayText: c.text,
      targetClaimId: c.claim_id,
    });
  }

  // 5. Cross-Examination & Defenses
  if (trial.attacks.length > 0) {
    items.push({
      id: "court-cross-exam",
      agent: "court",
      phase: "intro",
      title: "Cross-Examination Phase",
      badge: "Cross-Exam",
      spokenText: "We now enter cross-examination. Advocates shall challenge opposing claims and present rebuttals.",
      displayText: "Cross-examination of contested evidence and counter-arguments.",
    });

    for (const a of trial.attacks) {
      const attackerName = agentName(a.attacker);
      items.push({
        id: `attack-${a.attack_id}`,
        agent: a.attacker === "thor" ? "thor" : "loki",
        phase: "attack",
        title: `${attackerName} · Challenge on ${a.target_claim_id}`,
        badge: `Attack ${a.attack_id}`,
        spokenText: `${attackerName} challenges claim ${a.target_claim_id}. ${a.objection}. ${
          a.evidence_gap ? `Noting evidence gap: ${a.evidence_gap}.` : ""
        }`,
        displayText: `${attackerName} on ${a.target_claim_id}: ${a.objection}`,
        targetClaimId: a.target_claim_id,
      });

      // Defenses or Concessions for this attack
      const defenses = trial.defenses.filter((d) => d.attack_id === a.attack_id);
      const concessions = trial.concessions.filter((c) => c.attack_id === a.attack_id);

      for (const d of defenses) {
        const defenderName = agentName(d.defender);
        items.push({
          id: `defense-${d.defense_id}`,
          agent: d.defender === "thor" ? "thor" : "loki",
          phase: "defense",
          title: `${defenderName} · Defense`,
          badge: "New Evidence",
          spokenText: `${defenderName} responds with new evidence. ${d.argument}`,
          displayText: `${defenderName} defends: ${d.argument}`,
          targetClaimId: a.target_claim_id,
        });
      }

      for (const c of concessions) {
        const agentN = agentName(c.agent);
        items.push({
          id: `concession-${c.concession_id}`,
          agent: c.agent === "thor" ? "thor" : "loki",
          phase: "concession",
          title: `${agentN} · Concession`,
          badge: c.partial ? "Partial Concession" : "Full Concession",
          spokenText: `${agentN} concedes${c.partial ? " in part" : ""}. ${c.reason}`,
          displayText: `${agentN} concedes: ${c.reason}`,
          targetClaimId: a.target_claim_id,
        });
      }
    }
  }

  // 6. Odin's Sovereign Rulings
  const ruledClaims = Object.entries(trial.rulings);
  if (ruledClaims.length > 0) {
    items.push({
      id: "court-rulings-intro",
      agent: "court",
      phase: "intro",
      title: "Odin's Rulings",
      badge: "Sovereign Decrees",
      spokenText: "Silence in the court. The All-Father Odin delivers his final rulings on each claim.",
      displayText: "Odin evaluates each claim and delivers binding rulings.",
    });

    for (const [, rulings] of ruledClaims) {
      const latest = rulings[rulings.length - 1];
      if (!latest) continue;

      items.push({
        id: `ruling-${latest.claim_id}`,
        agent: "odin",
        phase: "ruling",
        title: `Odin · Ruling on ${latest.claim_id}`,
        badge: latest.verdict.toUpperCase(),
        spokenText: `Odin rules on claim ${latest.claim_id}. Verdict: ${latest.verdict}. ${latest.rationale}`,
        displayText: `Verdict: ${latest.verdict.toUpperCase()}. ${latest.rationale}`,
        targetClaimId: latest.claim_id,
      });
    }
  }

  // 7. Conclusion / Send-back notice
  if (trial.sendbacks.length > 0) {
    items.push({
      id: "odin-sendback",
      agent: "odin",
      phase: "conclusion",
      title: "Odin · Send-Back Order",
      badge: "Second Run Ordered",
      spokenText: "Odin finds essential trade data incomplete. The court orders Heimdall to conduct new research.",
      displayText: "Case sent back for further intelligence gathering before final judgment.",
    });
  } else {
    items.push({
      id: "court-closing",
      agent: "court",
      phase: "conclusion",
      title: "Adjournment",
      badge: "Decree Final",
      spokenText: "The proceedings of the Nine Realms are concluded. Rulings stand entered into the Imperial Archive.",
      displayText: "The trial is adjourned. All findings entered into the final intelligence briefing.",
    });
  }

  return items;
}
