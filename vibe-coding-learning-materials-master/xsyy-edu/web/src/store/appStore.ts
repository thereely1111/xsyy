import { create } from 'zustand';
import { api } from '../lib/api';
import { getOrCreateDeviceId } from '../lib/device';
import type {
  AgreementDocType,
  AgreementRecord,
  CommissionSummary,
  FeedbackItem,
  InviteInfo,
  QuotaInfo,
  WelfarePolicy,
  SystemMessageItem,
  UserInfo,
  AnnouncementItem,
} from '../types';

const TOKEN_KEY = 'xsyy_auth_token';
const USER_KEY = 'xsyy_current_user';
const AGREEMENT_RECORDS_KEY = 'xsyy_user_agreements_v1';
const SYSTEM_MESSAGES_KEY = 'xsyy_system_messages_v1';
const ACKED_ANNOUNCEMENTS_KEY = 'xsyy_acked_announcements_v1';
const FEEDBACKS_KEY = 'xsyy_feedbacks_v1';
const GENERATED_CONTENTS_KEY = 'xsyy_generated_contents_v1';
const LAST_LOGIN_DATE_KEY = 'xsyy_last_login_date_v1';

export const AGREEMENT_VERSION = 'v1.0.0';
export const AGREEMENT_LAST_UPDATED = '2026-05-01';

export interface ToastItem {
  id: number;
  type: 'success' | 'error' | 'info';
  message: string;
}

interface GeneratedContentItem {
  taskId: string;
  question: string;
  createdAt: string;
}

type UserMap<T> = Record<string, T>;

interface AgreementModalState {
  open: boolean;
  docType: AgreementDocType;
}

interface AppState {
  deviceId: string;
  authToken: string | null;
  currentUser: UserInfo | null;
  quota: QuotaInfo | null;
  inviteInfo: InviteInfo | null;
  welfarePolicy: WelfarePolicy | null;
  commissionSummary: CommissionSummary | null;
  authModalOpen: boolean;
  inviteModalOpen: boolean;
  accountCenterOpen: boolean;
  commissionModalOpen: boolean;
  systemMessagesOpen: boolean;
  feedbackModalOpen: boolean;
  agreementModal: AgreementModalState;
  firstGiftVisible: boolean;
  firstGiftReward: number;
  toasts: ToastItem[];
  requestLoading: boolean;
  prompt: string;
  systemMessages: SystemMessageItem[];
  announcements: AnnouncementItem[];
  ackedAnnouncementIds: string[];
  feedbacks: FeedbackItem[];
  generatedContents: GeneratedContentItem[];
  init: () => Promise<void>;
  setPrompt: (value: string) => void;
  openAuthModal: () => void;
  closeAuthModal: () => void;
  openAgreementModal: (docType: AgreementDocType) => void;
  closeAgreementModal: () => void;
  openAccountCenter: () => void;
  closeAccountCenter: () => void;
  openCommissionModal: () => Promise<void>;
  closeCommissionModal: () => void;
  refreshCommission: () => Promise<void>;
  openSystemMessages: () => void;
  closeSystemMessages: () => void;
  openFeedbackModal: () => void;
  closeFeedbackModal: () => void;
  openInviteModal: () => Promise<void>;
  closeInviteModal: () => void;
  addToast: (message: string, type?: ToastItem['type']) => void;
  removeToast: (id: number) => void;
  logout: () => void;
  deleteAccount: () => Promise<void>;
  refreshQuota: () => Promise<void>;
  consumeAndRequestGeneration: () => Promise<void>;
  loginSuccess: (payload: { token: string; user: UserInfo; quota: QuotaInfo; inviteInfo: InviteInfo; firstLoginReward?: number; showGift?: boolean }) => void;
  recordAgreementAccepted: (userId: string) => void;
  checkAndSendDailyResetMessage: (userId: string) => void;
  markSystemMessageRead: (messageId: string) => void;
  clearSystemMessages: () => void;
  fetchAnnouncements: () => Promise<void>;
  ackAnnouncement: (id: number | string) => void;
  ackAllAnnouncements: () => void;
  submitFeedback: (description: string, images: string[]) => void;
}

function safeParse<T>(raw: string | null): T | null {
  if (!raw) return null;
  try {
    return JSON.parse(raw) as T;
  } catch {
    return null;
  }
}

function loadRecord<T>(key: string): UserMap<T> {
  const data = safeParse<UserMap<T>>(localStorage.getItem(key));
  return data ?? {};
}

function saveRecord<T>(key: string, data: UserMap<T>): void {
  localStorage.setItem(key, JSON.stringify(data));
}

function loadArray<T>(key: string): T[] {
  const data = safeParse<T[]>(localStorage.getItem(key));
  return data ?? [];
}

function saveArray<T>(key: string, data: T[]): void {
  localStorage.setItem(key, JSON.stringify(data));
}

function todayIsoDate(): string {
  return new Date().toISOString().slice(0, 10);
}

// 公告轮询守卫：仅启动一次
let announcementPollingStarted = false;

export const useAppStore = create<AppState>((set, get) => ({
  deviceId: getOrCreateDeviceId(),
  authToken: localStorage.getItem(TOKEN_KEY),
  currentUser: safeParse<UserInfo>(localStorage.getItem(USER_KEY)),
  quota: null,
  inviteInfo: null,
  welfarePolicy: null,
  commissionSummary: null,
  authModalOpen: false,
  inviteModalOpen: false,
  accountCenterOpen: false,
  commissionModalOpen: false,
  systemMessagesOpen: false,
  feedbackModalOpen: false,
  agreementModal: { open: false, docType: 'user' },
  firstGiftVisible: false,
  firstGiftReward: 0,
  toasts: [],
  requestLoading: false,
  prompt: '',
  systemMessages: [],
  announcements: [],
  ackedAnnouncementIds: loadArray<string>(ACKED_ANNOUNCEMENTS_KEY),
  feedbacks: loadArray<FeedbackItem>(FEEDBACKS_KEY),
  generatedContents: loadArray<GeneratedContentItem>(GENERATED_CONTENTS_KEY),

  async init() {
    await get().refreshQuota();
    try {
      const welfarePolicy = await api.getWelfarePolicy();
      set({ welfarePolicy });
    } catch {
      // 福利政策接口不可用时使用邀请信息中的默认值
    }
    if (get().authToken) {
      try {
        const inviteInfo = await api.getInviteInfo(get().authToken as string);
        const currentUser = get().currentUser;
        if (currentUser?.userId) {
          get().checkAndSendDailyResetMessage(currentUser.userId);
          const messageRecord = loadRecord<SystemMessageItem[]>(SYSTEM_MESSAGES_KEY);
          set({ systemMessages: messageRecord[currentUser.userId] ?? [] });
        }
        set({ inviteInfo });
      } catch {
        // ignore token fallback here
      }
    }

    // 拉取管理后台发布的公告（对接系统消息模块），并定时轮询
    void get().fetchAnnouncements();
    if (!announcementPollingStarted) {
      announcementPollingStarted = true;
      setInterval(() => {
        void get().fetchAnnouncements();
      }, 30000);
    }
  },

  setPrompt(value) {
    set({ prompt: value });
  },

  openAuthModal() {
    set({ authModalOpen: true });
  },

  closeAuthModal() {
    set({ authModalOpen: false });
  },

  openAgreementModal(docType) {
    set({ agreementModal: { open: true, docType } });
  },

  closeAgreementModal() {
    set({ agreementModal: { ...get().agreementModal, open: false } });
  },

  openAccountCenter() {
    set({ accountCenterOpen: true });
    void get().refreshCommission();
  },

  closeAccountCenter() {
    set({ accountCenterOpen: false });
  },

  async openCommissionModal() {
    const token = get().authToken;
    if (!token) {
      get().addToast('请先登录', 'error');
      return;
    }
    try {
      await get().refreshCommission();
      set({ commissionModalOpen: true });
    } catch (error) {
      get().addToast((error as Error).message, 'error');
    }
  },

  closeCommissionModal() {
    set({ commissionModalOpen: false });
  },

  async refreshCommission() {
    const token = get().authToken;
    if (!token) return;
    try {
      const summary = await api.getCommissionSummary(token);
      set({ commissionSummary: summary });
    } catch (error) {
      // 忽略静默失败（未登录等场景）
    }
  },

  openSystemMessages() {
    const currentUser = get().currentUser;
    if (!currentUser?.userId) {
      get().addToast('请先登录', 'error');
      return;
    }
    const messageRecord = loadRecord<SystemMessageItem[]>(SYSTEM_MESSAGES_KEY);
    set({ systemMessagesOpen: true, systemMessages: messageRecord[currentUser.userId] ?? [] });
    // 打开系统消息即视为已读公告，清除对应红点
    get().ackAllAnnouncements();
  },

  closeSystemMessages() {
    set({ systemMessagesOpen: false });
  },

  openFeedbackModal() {
    const currentUser = get().currentUser;
    if (!currentUser?.userId) {
      get().addToast('请先登录', 'error');
      return;
    }
    set({ feedbackModalOpen: true });
  },

  closeFeedbackModal() {
    set({ feedbackModalOpen: false });
  },

  async openInviteModal() {
    const token = get().authToken;
    if (!token) {
      get().addToast('请先登录后查看邀请有礼', 'error');
      set({ authModalOpen: true });
      return;
    }
    const inviteInfo = await api.getInviteInfo(token);
    set({ inviteModalOpen: true, inviteInfo });
  },

  closeInviteModal() {
    set({ inviteModalOpen: false });
  },

  addToast(message, type = 'info') {
    const id = Date.now() + Math.floor(Math.random() * 1000);
    set((state) => ({ toasts: [...state.toasts, { id, type, message }] }));
    window.setTimeout(() => {
      get().removeToast(id);
    }, 2600);
  },

  removeToast(id) {
    set((state) => ({ toasts: state.toasts.filter((item) => item.id !== id) }));
  },

  logout() {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(USER_KEY);
    set({
      authToken: null,
      currentUser: null,
      inviteInfo: null,
      commissionSummary: null,
      inviteModalOpen: false,
      systemMessages: [],
      accountCenterOpen: false,
      commissionModalOpen: false,
      systemMessagesOpen: false,
      feedbackModalOpen: false,
    });
    void get().refreshQuota();
  },

  async deleteAccount() {
    const token = get().authToken;
    const userId = get().currentUser?.userId;
    if (!token || !userId) {
      get().addToast('请先登录', 'error');
      return;
    }

    try {
      await api.deleteAccount(token);

      const agreementRecord = loadRecord<AgreementRecord>(AGREEMENT_RECORDS_KEY);
      delete agreementRecord[userId];
      saveRecord<AgreementRecord>(AGREEMENT_RECORDS_KEY, agreementRecord);

      const messageRecord = loadRecord<SystemMessageItem[]>(SYSTEM_MESSAGES_KEY);
      delete messageRecord[userId];
      saveRecord<SystemMessageItem[]>(SYSTEM_MESSAGES_KEY, messageRecord);

      const loginRecord = loadRecord<string>(LAST_LOGIN_DATE_KEY);
      delete loginRecord[userId];
      saveRecord<string>(LAST_LOGIN_DATE_KEY, loginRecord);

      const allFeedbacks = loadArray<FeedbackItem>(FEEDBACKS_KEY);
      const filteredFeedbacks = allFeedbacks.filter((item) => item.userId !== userId);
      saveArray<FeedbackItem>(FEEDBACKS_KEY, filteredFeedbacks);

      saveArray<GeneratedContentItem>(GENERATED_CONTENTS_KEY, []);

      const extraLocalKeys = [
        'xsyy_invite_progress',
        'xsyy_extra_balance',
        'xsyy_system_messages',
        'xsyy_feedbacks',
        'xsyy_user_data',
      ];
      extraLocalKeys.forEach((key) => {
        localStorage.removeItem(key);
      });

      localStorage.removeItem(TOKEN_KEY);
      localStorage.removeItem(USER_KEY);

      set({
        authToken: null,
        currentUser: null,
        inviteInfo: null,
        quota: null,
        commissionSummary: null,
        authModalOpen: false,
        inviteModalOpen: false,
        accountCenterOpen: false,
        commissionModalOpen: false,
        systemMessagesOpen: false,
        feedbackModalOpen: false,
        systemMessages: [],
        generatedContents: [],
      });

      await get().refreshQuota();
      get().addToast('账号已注销，相关数据已清除', 'success');
      window.location.href = '/';
    } catch (error) {
      get().addToast((error as Error).message || '注销失败，请稍后重试', 'error');
    }
  },

  async refreshQuota() {
    try {
      const quota = await api.getQuota(get().deviceId, get().authToken ?? undefined);
      set({ quota });
    } catch (error) {
      get().addToast((error as Error).message, 'error');
    }
  },

  async consumeAndRequestGeneration() {
    const prompt = get().prompt.trim();
    if (!prompt) {
      get().addToast('请先输入任务创建需求', 'error');
      return;
    }

    set({ requestLoading: true });
    try {
      const result = await api.requestGeneration(
        { prompt, deviceId: get().deviceId },
        get().authToken ?? undefined,
      );
      const currentContents = loadArray<GeneratedContentItem>(GENERATED_CONTENTS_KEY);
      const nextContents = [
        {
          taskId: result.requestId,
          question: prompt,
          createdAt: new Date().toISOString(),
        },
        ...currentContents,
      ].slice(0, 500);
      saveArray<GeneratedContentItem>(GENERATED_CONTENTS_KEY, nextContents);

      set({ quota: result.quota, prompt: '' });
      set({ generatedContents: nextContents });
      get().addToast(
        `本次生成消耗 1 次，剩余总次数：${result.quota.remainingTotal} 次`,
        'success',
      );
    } catch (error) {
      get().addToast((error as Error).message, 'error');
    } finally {
      set({ requestLoading: false });
    }
  },

  loginSuccess(payload) {
    localStorage.setItem(TOKEN_KEY, payload.token);
    localStorage.setItem(USER_KEY, JSON.stringify(payload.user));
    get().checkAndSendDailyResetMessage(payload.user.userId);

    const messageRecord = loadRecord<SystemMessageItem[]>(SYSTEM_MESSAGES_KEY);
    set({
      authToken: payload.token,
      currentUser: payload.user,
      quota: payload.quota,
      inviteInfo: payload.inviteInfo,
      authModalOpen: false,
      firstGiftVisible: Boolean(payload.showGift),
      firstGiftReward: payload.firstLoginReward ?? 0,
      systemMessages: messageRecord[payload.user.userId] ?? [],
    });
    if (payload.showGift && (payload.firstLoginReward ?? 0) > 0) {
      // 展示后端实际发放的注册赠送额度（与后台系统配置 new_user_gift_quota 同步）
      get().addToast(`注册成功，已赠送 ${payload.firstLoginReward} 次使用额度`, 'success');
      window.setTimeout(() => set({ firstGiftVisible: false, firstGiftReward: 0 }), 2000);
    }
  },

  recordAgreementAccepted(userId) {
    const next: AgreementRecord = {
      userId,
      agreedAt: new Date().toISOString(),
      agreementVersion: AGREEMENT_VERSION,
    };
    const records = loadRecord<AgreementRecord>(AGREEMENT_RECORDS_KEY);
    records[userId] = next;
    saveRecord<AgreementRecord>(AGREEMENT_RECORDS_KEY, records);
  },

  checkAndSendDailyResetMessage(userId) {
    if (!userId) return;

    const today = todayIsoDate();
    const loginRecord = loadRecord<string>(LAST_LOGIN_DATE_KEY);
    if (loginRecord[userId] === today) return;

    loginRecord[userId] = today;
    saveRecord<string>(LAST_LOGIN_DATE_KEY, loginRecord);

    const messageRecord = loadRecord<SystemMessageItem[]>(SYSTEM_MESSAGES_KEY);
    const list = messageRecord[userId] ?? [];
    const item: SystemMessageItem = {
      id: `${Date.now()}-${Math.floor(Math.random() * 1000)}`,
      content: '今日免费生成次数已刷新',
      createdAt: new Date().toISOString(),
      read: false,
    };
    messageRecord[userId] = [item, ...list].slice(0, 200);
    saveRecord<SystemMessageItem[]>(SYSTEM_MESSAGES_KEY, messageRecord);

    if (get().currentUser?.userId === userId) {
      set({ systemMessages: messageRecord[userId] });
    }
  },

  markSystemMessageRead(messageId) {
    const currentUser = get().currentUser;
    if (!currentUser?.userId) return;

    const messageRecord = loadRecord<SystemMessageItem[]>(SYSTEM_MESSAGES_KEY);
    const nextList = (messageRecord[currentUser.userId] ?? []).map((item) =>
      item.id === messageId ? { ...item, read: true } : item,
    );
    messageRecord[currentUser.userId] = nextList;
    saveRecord<SystemMessageItem[]>(SYSTEM_MESSAGES_KEY, messageRecord);
    set({ systemMessages: nextList });
  },

  clearSystemMessages() {
    const currentUser = get().currentUser;
    if (!currentUser?.userId) return;
    const messageRecord = loadRecord<SystemMessageItem[]>(SYSTEM_MESSAGES_KEY);
    messageRecord[currentUser.userId] = [];
    saveRecord<SystemMessageItem[]>(SYSTEM_MESSAGES_KEY, messageRecord);
    set({ systemMessages: [] });
  },

  async fetchAnnouncements() {
    const token = get().authToken;
    if (!token) {
      set({ announcements: [] });
      return;
    }
    try {
      const data = await api.getAnnouncements(token);
      set({ announcements: data.announcements ?? [] });
    } catch {
      // 静默失败（未登录 / 离线等场景）
    }
  },

  ackAnnouncement(id) {
    const key = String(id);
    const acked = loadArray<string>(ACKED_ANNOUNCEMENTS_KEY);
    if (!acked.includes(key)) {
      acked.push(key);
      saveArray<string>(ACKED_ANNOUNCEMENTS_KEY, acked);
    }
    set({ ackedAnnouncementIds: acked });
  },

  ackAllAnnouncements() {
    const current = loadArray<string>(ACKED_ANNOUNCEMENTS_KEY);
    const merged = Array.from(
      new Set<string>([...current, ...get().announcements.map((a) => String(a.id))]),
    );
    saveArray<string>(ACKED_ANNOUNCEMENTS_KEY, merged);
    set({ ackedAnnouncementIds: merged });
  },

  submitFeedback(description, images) {
    const currentUser = get().currentUser;
    if (!currentUser?.userId) {
      get().addToast('请先登录', 'error');
      return;
    }

    const nextItem: FeedbackItem = {
      id: `${Date.now()}-${Math.floor(Math.random() * 1000)}`,
      userId: currentUser.userId,
      description,
      images,
      createdAt: new Date().toISOString(),
    };

    const allFeedbacks = [nextItem, ...loadArray<FeedbackItem>(FEEDBACKS_KEY)].slice(0, 500);
    saveArray<FeedbackItem>(FEEDBACKS_KEY, allFeedbacks);
    set({ feedbacks: allFeedbacks, feedbackModalOpen: false });
    get().addToast('反馈已提交，感谢您的建议！', 'success');
  },
}));
