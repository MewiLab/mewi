export type ReportProduct = 'attachment' | 'recommendation';

export type GenerationMode = 'llm+kb' | 'llm_only' | 'deterministic';

export type PlayerCatAction =
  | 'player_play_invite'
  | 'player_meow'
  | 'player_nod_yes'
  | 'player_shake_no'
  | 'player_sit_near'
  | 'player_groom'
  | 'player_poop'
  | 'player_pee'
  | 'player_scratch'
  | 'player_lie'
  | 'player_sleep'
  | 'player_smell'
  | 'player_look_around'
  | 'player_alert'
  | 'player_push'
  | 'player_shake'
  | 'player_dig'
  | 'player_crawl'
  | 'player_drink'
  | 'player_flinch'
  | 'player_startle'
  | 'player_stun'
  | 'player_open_chest'
  | 'player_eat'
  | 'player_attack';

export type PlayerActionFamily =
  | 'affiliative_bid'
  | 'calm_presence'
  | 'cautious_investigation'
  | 'exploration_resource'
  | 'boundary_refusal'
  | 'intrusion_threat'
  | 'fear_startle_shutdown'
  | 'unknown';

export type ReportRoute = {
  dataFileId: string;
  routeId: string;
  displayName: string;
};

export type ReportBar = {
  label: string;
  value: number;
  color?: string;
};

export type AttachmentAnalysis = {
  type?: string;
  modifier?: string;
  confidence?: string;
  scores?: {
    secure?: number;
    anxious?: number;
    avoidant?: number;
    fearful_avoidant?: number;
  };
  summary?: string;
  evidence?: Array<{ label: string; detail: string }>;
  caveat?: string;
};

export type InteractionSignature = {
  action_counts?: Partial<Record<PlayerCatAction | string, number>>;
  action_family_pct?: Partial<Record<PlayerActionFamily, number>>;
  target_distribution?: Record<string, number>;
  ignored_actions?: string[];
};

export type GestureResponseChain = {
  correlation_id?: string;
  source_event_id?: string;
  player_action?: PlayerCatAction | string;
  action_family?: PlayerActionFamily;
  target_id?: string;
  delivered?: boolean;
  cat_reaction?: string;
  reaction_event_id?: string;
  reaction_latency_s?: number | null;
  trust_delta?: number | null;
  phase?: string;
  status?: string;
  confidence?: number;
  facing_dot?: number;
  evidence_event_ids?: string[];
};

export type AttachmentFeature = ReportBar & {
  evidence_event_ids?: string[];
};

export type ReportCat = {
  name: string;
  accent: string;
  archetype?: string;
  trait?: string;
  trust_arc?: number[];
  delta?: string;
  status?: string;
  bars?: ReportBar[];
  sequence_log?: Array<{ ts: string; actor: 'H' | 'C'; action: string; trigger?: string }>;
  moments?: Array<{ session: string; event: string; highlight?: boolean; milestone?: string | null }>;
};

export type ProcessedAttachmentReport = {
  user_id: string;
  generation_mode?: GenerationMode;
  user?: {
    id?: string;
    display_name?: string;
    handle?: string;
    report_slug?: string;
  };
  meta?: { sessions?: number; total_events?: number; last_seen?: string; variant_label?: string };
  summary?: {
    avg_trust_gained?: number;
    primary_bond?: string;
    avg_reaction_latency_s?: number;
    patience_pct?: number;
  };
  cats?: Record<string, ReportCat>;
  radar?: Record<string, number>;
  attention_pct?: Record<string, number>;
  multi_cat_encounters?: Array<{ situation: string; choice: string; freq: string; outcome: string }>;
  interaction_signature?: InteractionSignature;
  gesture_response_chains?: GestureResponseChain[];
  attachment_features?: AttachmentFeature[];
  attachment_profile?: ReportBar[];
  attachment_analysis?: AttachmentAnalysis;
  timeline?: Array<{ session: string; event: string; highlight?: boolean; milestone?: string | null }>;
  recommendation?: RecommendationBlock;
};

export type RecommendationBlock = Record<string, unknown>;

export type RecommendationReport = {
  user_id: string;
  generation_mode?: GenerationMode;
  recommendation: RecommendationBlock;
};

export type FrontendReport = ProcessedAttachmentReport | RecommendationReport;

export function isAttachmentReport(report: FrontendReport | null): report is ProcessedAttachmentReport {
  return !!report && 'cats' in report;
}
