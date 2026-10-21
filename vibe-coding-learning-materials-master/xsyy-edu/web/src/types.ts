export interface UserInfo {
  userId: string;
  username: string;
  phone?: string;
  inviteCode: string;
}

export interface SubscriptionInfo {
  plan: 'monthly' | 'quarterly' | 'yearly';
  expire_at: string;
}

export interface QuotaInfo {
  dailyFreeUsed: number;
  dailyFreeLimit: number;
  freeBalance?: number;
  paidBalance?: number;
  extraBalance: number;
  remainingTotal: number;
  lastResetDate?: string;
  isLoggedIn?: boolean;
  subscription?: SubscriptionInfo | null;
}

// 邀请有礼：奖励次数由管理后台福利配置动态下发
export interface InviteInfo {
  inviteCode: string;
  invitedCount: number;
  inviteRewardQuota: number;
  newUserGiftQuota?: number;
}

export interface WelfarePolicy {
  newUserGiftQuota: number;
  inviteRewardQuota: number;
}

// 返利账户汇总（金额单位：分，展示时除以100转为元）
export interface CommissionSummary {
  totalReward: number;      // 累计返利
  withdrawnAmount: number;  // 已提现或已抵扣
  pendingAmount: number;    // 提现中或订单锁定
  availableAmount: number;  // 可提现或可抵扣
}

export interface RechargeOrderQuote {
  success: boolean;
  plan: 'monthly' | 'quarterly' | 'yearly';
  plan_name: string;
  total_price: number;
  total_price_fen: number;
  commission_available: number;
  commission_used: number;
  cash_due: number;
  duration_days: number;
}

// 返利来源明细（每笔返利）
export interface CommissionRecordItem {
  id: number;
  sourceUserId: string;
  sourceUsername: string | null;   // 来源用户（触发返利的新用户）
  sourceInviteCode?: string | null; // 来源用户的邀请码
  inviterUsername: string | null;  // 直接邀请者
  inviterInviteCode?: string | null; // 直接邀请者的邀请码
  level: number;                   // 层级 1/2/3
  amount: number;                  // 返利金额（分）
  status: string;
  createdAt: string | null;
}

export interface CommissionRecordsResult {
  items: CommissionRecordItem[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}

// 提现申请记录
export interface WithdrawalRecordItem {
  requestId: string;
  amount: number;          // 分
  status: string;          // pending / approved / rejected
  adminNote: string | null;
  createdAt: string | null;
  processedAt: string | null;
}

export interface SearchQuestionItem {
  taskId: string;
  question: string;
}

export type AgreementDocType = 'user' | 'privacy';

export interface AgreementRecord {
  userId: string;
  agreedAt: string;
  agreementVersion: string;
}

export interface SystemMessageItem {
  id: string;
  content: string;
  createdAt: string;
  read: boolean;
}

// 管理后台发布的公告（对接前端系统消息模块）
export interface AnnouncementItem {
  id: number;
  title: string;
  content: string;
  imageUrl: string | null;
  isPublished: boolean;
  publishedBy: string;
  createdAt: string;
}

export interface FeedbackItem {
  id: string;
  userId: string;
  description: string;
  images: string[];
  createdAt: string;
}
