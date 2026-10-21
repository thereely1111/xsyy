// @charset "UTF-8";
// 动态创建登录弹框 HTML
function initAuthModal() {
    // 如果已经存在，不重复创建
    if (document.getElementById('loginModal')) {
        return;
    }

    // 预读 URL 中的邀请码，用于注册表单默认值
    const urlInviteCode = (function () {
        try {
            const params = new URLSearchParams(window.location.search);
            return (params.get('inviteCode') || '').trim();
        } catch (e) {
            return '';
        }
    })();
    const storageInviteCode = (function () {
        try {
            return (localStorage.getItem('user_invite_code') || '').trim();
        } catch (e) {
            return '';
        }
    })();
    const defaultInviteCode = '';  // 邀请码不自动填入，保持空白由用户手动填写

    // 创建登录弹框 HTML
    const modalHTML = `
    <div id="loginModal" class="modal-overlay">
        <div class="modal">
            <button class="close-btn" onclick="hideLoginModal()">×</button>
            
            <div class="modal-header">
                <h2>象数演易</h2>
                <p>欢迎回来</p>
            </div>
            
            <div class="modal-tabs">
                <button class="modal-tab active" onclick="switchTab('login')">登录</button>
                <button class="modal-tab" onclick="switchTab('register')">注册</button>
            </div>
            
            <!-- 登录表单 -->
            <div id="loginTab" class="modal-tab-content active">
                <form id="loginForm" onsubmit="handleLogin(event)">
                    <div class="form-group">
                        <label>用户名</label>
                        <input type="text" id="loginUsername" required>
                    </div>
                    <div class="form-group">
                        <label>密码</label>
                        <input type="password" id="loginPassword" required>
                    </div>
                    <label class="agreement-row">
                        <input type="checkbox" id="loginAgreementCheckbox">
                        <span>
                            我已阅读并同意
                            <a href="#" class="agreement-link" onclick="event.preventDefault(); window.openAgreementModal && window.openAgreementModal('user')">《用户协议》</a>
                            和
                            <a href="#" class="agreement-link" onclick="event.preventDefault(); window.openAgreementModal && window.openAgreementModal('privacy')">《隐私政策》</a>
                        </span>
                    </label>
                    <div class="error-message" id="loginError"></div>
                    <button type="submit" class="modal-btn" id="loginBtn">登录</button>
                </form>
                <div class="modal-link">
                    <a href="#" onclick="switchTab('forgot'); return false;">忘记密码？</a>
                    <span style="margin: 0 8px; color: var(--ink-grey);">|</span>
                    <a href="#" onclick="switchTab('register'); return false;">没有账号？→去注册</a>
                </div>
            </div>
            
            <!-- 注册表单 -->
            <div id="registerTab" class="modal-tab-content">
                <!-- 注册方式选择 -->
                <div class="register-method-tabs" style="display: flex; gap: 10px; margin-bottom: 20px; border-bottom: 2px solid var(--border-color);">
                    <button type="button" class="register-method-tab active" onclick="switchRegisterMethod('password')">用户名密码</button>
                    <button type="button" class="register-method-tab disabled-tab-style" disabled onclick="switchRegisterMethod('phone')">手机验证码</button>
                </div>
                
                <!-- 用户名密码注册 -->
                <div id="registerPasswordForm" class="register-method-content active">
                    <form id="registerForm" onsubmit="console.log('【HTML onsubmit 属性】被触发！', event); return handleRegisterPassword(event);">
                        <div class="form-group">
                            <label>用户名</label>
                            <input type="text" id="registerUsername" required>
                        </div>
                        <div class="form-group">
                            <label>密码</label>
                            <input type="password" id="registerPassword" required minlength="6">
                        </div>
                        <div class="form-group">
                            <label>确认密码</label>
                            <input type="password" id="registerPasswordConfirm" required minlength="6">
                        </div>
                        <div class="form-row register-invite-grade-row" style="display:flex; flex-wrap:wrap; gap:16px; margin-bottom: 0;">
                            <div class="form-group" style="flex:1 1 160px; min-width:0; margin-bottom:0;">
                                <label>邀请码</label>
                                <input type="text" id="registerBetaCode" required placeholder="请输入邀请码" value="${defaultInviteCode.replace(/"/g, '&quot;')}" autocomplete="off">
                            </div>
                            <div class="form-group" style="flex:1 1 160px; min-width:0; margin-bottom:0;">
                                <label>所在年级（选填）</label>
                                <select id="registerGrade">
                                    <option value="">请选择年级（选填）</option>
                                    <option value="1">一年级</option>
                                    <option value="2">二年级</option>
                                    <option value="3">三年级</option>
                                    <option value="4">四年级</option>
                                    <option value="5">五年级</option>
                                    <option value="6">六年级</option>
                                    <option value="7">七年级</option>
                                    <option value="8">八年级</option>
                                    <option value="9">九年级</option>
                                </select>
                            </div>
                        </div>

                        <p style="color: var(--primary-red); font-size: 12px; margin-top: 5px; margin-bottom: 0;">注册需填写有效邀请码（官方邀请码：XSYY2026）</p>

                        <label class="agreement-row">
                            <input type="checkbox" id="registerAgreementCheckbox">
                            <span>
                                我已阅读并同意
                                <a href="#" class="agreement-link" onclick="event.preventDefault(); window.openAgreementModal && window.openAgreementModal('user')">《用户协议》</a>
                                和
                                <a href="#" class="agreement-link" onclick="event.preventDefault(); window.openAgreementModal && window.openAgreementModal('privacy')">《隐私政策》</a>
                            </span>
                        </label>
                        <div class="error-message" id="registerError"></div>
                        <div class="success-message" id="registerSuccess"></div>
                        <button type="submit" class="modal-btn" id="registerBtn">注册</button>
                    </form>
                </div>
                
                <!-- 手机验证码注册 -->
                <div id="registerPhoneForm" class="register-method-content">
                    <div style="text-align: center; padding: 20px; color: var(--ink-black); background: #fff3cd; border: 1px solid #ffc107; border-radius: 8px; margin-bottom: 20px;">
                        <p style="font-size: 14px; margin: 0; font-weight: 500;">⚠️ 该功能暂时关闭，请通过用户名密码和邀请码注册</p>
                    </div>
                    <form id="registerPhoneFormElement" onsubmit="event.preventDefault(); return false;">
                        <div class="form-group">
                            <label>手机号</label>
                            <div style="display: flex; gap: 10px;">
                                <input type="tel" id="registerPhone" required pattern="[0-9]{11}" placeholder="11位手机号" style="flex: 1;" disabled>
                                <button type="button" class="modal-btn" id="sendCodeBtn" onclick="return false;" style="width: auto; padding: 12px 20px; margin-top: 0; opacity: 0.5; cursor: not-allowed;" disabled>发送验证码</button>
                            </div>
                        </div>
                        <div class="form-group">
                            <label>验证码</label>
                            <input type="text" id="registerVerificationCode" required pattern="[0-9]{6}" placeholder="6位验证码" maxlength="6" disabled>
                        </div>
                        <label class="agreement-row" style="opacity:0.65;">
                            <input type="checkbox" id="registerPhoneAgreementCheckbox" disabled>
                            <span>
                                我已阅读并同意
                                <a href="#" class="agreement-link" onclick="event.preventDefault(); window.openAgreementModal && window.openAgreementModal('user')">《用户协议》</a>
                                和
                                <a href="#" class="agreement-link" onclick="event.preventDefault(); window.openAgreementModal && window.openAgreementModal('privacy')">《隐私政策》</a>
                            </span>
                        </label>
                        <div class="error-message" id="registerPhoneError"></div>
                        <div class="success-message" id="registerPhoneSuccess"></div>
                        <button type="submit" class="modal-btn" id="registerPhoneBtn" disabled style="opacity: 0.5; cursor: not-allowed;">注册</button>
                    </form>
                </div>
            </div>
            
            <!-- 忘记密码表单 -->
            <div id="forgotTab" class="modal-tab-content">
                <div style="text-align: center;">
                    <p style="margin: 0 0 12px; color: #555; line-height: 1.7;">请扫码联系客服工作人员，并提供您的用户 ID，由工作人员为您初始化密码。</p>
                    <img src="/images/illustrations/wechat_confirm_qr.webp" alt="客服微信二维码" style="display: block; width: min(260px, 100%); height: auto; margin: 0 auto 14px;">
                    <p style="margin: 0; color: #999; font-size: 13px; line-height: 1.6;">登录后可在个人信息中查看用户 ID</p>
                </div>
                <div class="modal-link">
                    <a href="#" onclick="switchTab('login'); return false;">返回登录</a>
                </div>
            </div>
            
            <!-- 重置密码表单 -->
            <div id="resetTab" class="modal-tab-content">
                <form id="resetForm" onsubmit="handleResetPassword(event)">
                    <div class="form-group">
                        <label>手机号</label>
                        <input type="tel" id="resetPhone" required pattern="[0-9]{11}" placeholder="11位手机号">
                    </div>
                    <div class="form-group">
                        <label>验证码</label>
                        <input type="text" id="resetVerificationCode" required pattern="[0-9]{6}" placeholder="6位验证码" maxlength="6">
                    </div>
                    <div class="form-group">
                        <label>新密码</label>
                        <input type="password" id="resetPassword" required minlength="6">
                    </div>
                    <div class="form-group">
                        <label>确认新密码</label>
                        <input type="password" id="resetPasswordConfirm" required minlength="6">
                    </div>
                    <div class="error-message" id="resetError"></div>
                    <div class="success-message" id="resetSuccess"></div>
                    <button type="submit" class="modal-btn" id="resetBtn">重置密码</button>
                </form>
                <div class="modal-link">
                    <a href="#" onclick="switchTab('login'); return false;">返回登录</a>
                </div>
            </div>
        </div>
    </div>
    `;
    
    // 插入到 body
    document.body.insertAdjacentHTML('beforeend', modalHTML);

    // DOM 创建后立即回填邀请码（兼容 auth.js 尚未加载完成的情况）
    (function tryFill(times) {
        if (times <= 0) return;
        if (typeof fillRegisterBetaCode === 'function') {
            fillRegisterBetaCode();
            return;
        }
        setTimeout(function () { tryFill(times - 1); }, 100);
    })(20);
}

if (typeof window !== 'undefined') {
    window.initAuthModal = initAuthModal;
}

