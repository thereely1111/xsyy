import type {
  CommissionRecordsResult,
  CommissionSummary,
  RechargeOrderQuote,
  InviteInfo,
  QuotaInfo,
  SearchQuestionItem,
  UserInfo,
  WithdrawalRecordItem,
  AnnouncementItem,
} from '../types';

export const API_BASE = (import.meta.env.VITE_API_BASE as string | undefined) || 'http://127.0.0.1:8000';

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: {
      'Content-Type': 'application/json',
      ...(options?.headers ?? {}),
    },
    ...options,
  });

  const contentType = response.headers.get('content-type') || '';
  const responseText = await response.text();
  const parseBody = <R,>(raw: string): R | string => {
    if (contentType.includes('application/json')) {
      return JSON.parse(raw) as R;
    }
    try {
      return JSON.parse(raw) as R;
    } catch {
      return raw;
    }
  };

  if (!response.ok) {
    let detail = '请求失败';
    try {
      const data = parseBody<{ detail?: string; message?: string }>(responseText);
      if (typeof data !== 'string') {
        detail = data.detail || data.message || detail;
      } else if (data.trim()) {
        detail = data;
      }
    } catch {
      // no-op
    }
    throw new Error(detail);
  }

  return parseBody<T>(responseText) as T;
}

function authHeaders(token?: string): HeadersInit {
  if (!token) {
    return {};
  }
  return { Authorization: `Bearer ${token}` };
}

export const api = {
  checkDeviceBinding(deviceId: string) {
    return request<{ isBound: boolean; boundUserId: string | null }>('/api/v2/device/check-binding', {
      method: 'POST',
      body: JSON.stringify({ deviceId }),
    });
  },

  validateInviteCode(inviteCode: string) {
    return request<{ isValid: boolean; isOfficial: boolean; inviterUserId: string | null }>('/api/v2/invite/validate', {
      method: 'POST',
      body: JSON.stringify({ inviteCode }),
    });
  },

  register(payload: {
    username: string;
    password: string;
    passwordConfirm: string;
    inviteCode: string;
    deviceId: string;
  }) {
    return request<{
      success: boolean;
      token: string;
      firstLoginRewardGranted: boolean;
      firstLoginReward: number;
      user: UserInfo;
      quota: QuotaInfo;
      inviteInfo: InviteInfo;
    }>('/api/v2/auth/register', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  },

  loginWithPassword(payload: { username: string; password: string; deviceId: string }) {
    return request<{ success: boolean; token: string; user: UserInfo; quota: QuotaInfo; inviteInfo: InviteInfo }>(
      '/api/v2/auth/login/password',
      {
        method: 'POST',
        body: JSON.stringify(payload),
      },
    );
  },

  loginWithPhone(payload: { phone: string; code: string; inviteCode?: string; deviceId: string }) {
    return request<{
      success: boolean;
      token: string;
      created: boolean;
      firstLoginRewardGranted: boolean;
      firstLoginReward: number;
      user: UserInfo;
      quota: QuotaInfo;
      inviteInfo: InviteInfo;
    }>('/api/v2/auth/login/phone', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  },

  getQuota(deviceId: string, token?: string) {
    const q = token ? '' : `?deviceId=${encodeURIComponent(deviceId)}`;
    return request<QuotaInfo>(`/api/v2/quota${q}`, {
      method: 'GET',
      headers: authHeaders(token),
    });
  },

  getWelfarePolicy() {
    return request<{ success: boolean; newUserGiftQuota: number; inviteRewardQuota: number }>('/api/v2/welfare-policy', {
      method: 'GET',
    });
  },

  getInviteInfo(token: string) {
    return request<InviteInfo>('/api/v2/invite/info', {
      method: 'GET',
      headers: authHeaders(token),
    });
  },

  getCommissionSummary(token: string) {
    return request<CommissionSummary & { success: boolean }>('/api/v2/commission/summary', {
      method: 'GET',
      headers: authHeaders(token),
    });
  },

  getRechargeOrderQuote(token: string, plan: RechargeOrderQuote['plan']) {
    return request<RechargeOrderQuote>(`/api/recharge-orders/quote?plan=${encodeURIComponent(plan)}`, {
      method: 'GET',
      headers: authHeaders(token),
    });
  },

  createRechargeOrder(token: string, payload: { plan: RechargeOrderQuote['plan']; price?: number; note?: string; use_commission?: boolean }) {
    return request<{ success: boolean; message: string; requestId: string }>('/api/recharge-orders', {
      method: 'POST',
      headers: authHeaders(token),
      body: JSON.stringify({ amount: 0, ...payload }),
    });
  },

  getCommissionRecords(token: string, page = 1, pageSize = 20) {
    return request<CommissionRecordsResult>(`/api/v2/commission/records?page=${page}&page_size=${pageSize}`, {
      method: 'GET',
      headers: authHeaders(token),
    });
  },

  getCommissionWithdrawals(token: string) {
    return request<{ success: boolean; items: WithdrawalRecordItem[] }>('/api/v2/commission/withdrawals', {
      method: 'GET',
      headers: authHeaders(token),
    });
  },

  withdrawCommission(token: string, amount: number) {
    return request<{ success: boolean; message: string } & CommissionSummary>('/api/v2/commission/withdraw', {
      method: 'POST',
      headers: authHeaders(token),
      body: JSON.stringify({ amount }),
    });
  },

  requestGeneration(payload: { prompt: string; deviceId: string }, token?: string) {
    return request<{ success: boolean; requestId: string; message: string; quota: QuotaInfo }>(
      '/api/v2/generation/request',
      {
        method: 'POST',
        headers: authHeaders(token),
        body: JSON.stringify(payload),
      },
    );
  },

  searchQuestions(payload: { query: string; limit?: number }) {
    return request<{ items: SearchQuestionItem[] }>('/api/v2/search/questions', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  },

  deleteAccount(token: string) {
    return request<{ success: boolean; message: string }>('/api/v2/account', {
      method: 'DELETE',
      headers: authHeaders(token),
    });
  },

  getAnnouncements(token: string) {
    return request<{ announcements: AnnouncementItem[] }>('/api/announcements', {
      method: 'GET',
      headers: authHeaders(token),
    });
  },

};
