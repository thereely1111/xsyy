/**
 * 知识点标签确认/选择弹窗
 *
 * 创建交互式教学动画完成后始终弹出，让用户确认大模型识别的标签：
 *   知识域 → 年级 → 章/单元 → 知识点标签（多选，隐性属性）
 * 用户确认后写入 knowledge_tags_confirmed=true，之后不再允许普通用户修改。
 */
(function (global) {
    "use strict";

    var frameworkData = null;
    var currentTaskId = null;
    var selectedSubTags = [];

    /**
     * 加载标签框架数据
     */
    async function loadFramework() {
        if (frameworkData) return frameworkData;
        try {
            var apiBase = global.API_BASE || "";
            var resp = await fetch(apiBase + "/api/knowledge-tag-framework");
            if (resp.ok) {
                frameworkData = await resp.json();
                return frameworkData;
            }
        } catch (e) {
            console.error("加载标签框架失败:", e);
        }
        return null;
    }

    /**
     * HTML 转义
     */
    function escapeHtml(text) {
        if (!text) return "";
        var div = document.createElement("div");
        div.textContent = String(text);
        return div.innerHTML;
    }

    /**
     * 创建弹窗 DOM
     */
    function createDialog(existingTags) {
        // 移除已有弹窗
        closeDialog();

        var overlay = document.createElement("div");
        overlay.className = "tag-dialog-overlay";
        overlay.id = "tagSelectionDialog";

        var dialog = document.createElement("div");
        dialog.className = "tag-dialog";

        var currentTags = existingTags && existingTags.knowledge_tags ? existingTags.knowledge_tags : existingTags;
        if (!currentTags || typeof currentTags !== "object" || Array.isArray(currentTags)) {
            currentTags = {};
        }

        var existingVersion = currentTags.version || "";
        var existingGrade = currentTags.grade || "";
        var existingMainTag = currentTags.main_tag || "";
        var existingSubTags = Array.isArray(currentTags.sub_tags) ? currentTags.sub_tags : [];
        selectedSubTags = [].concat(existingSubTags);

        dialog.innerHTML =
            '<div class="tag-dialog-header">' +
            "<h3>请确认知识点标签</h3>" +
            "<p>请核对系统识别的知识点标签，如不准确可修改后保存</p>" +
            "</div>" +
            '<div class="tag-dialog-body">' +
            '<div class="tag-dialog-field">' +
            "<label>知识域 <span class=\"required\">*</span></label>" +
            '<select id="tagDialogVersion"><option value="">请选择知识域</option></select>' +
            "</div>" +
            '<div class="tag-dialog-field">' +
            "<label>年级 <span class=\"required\">*</span></label>" +
            '<select id="tagDialogGrade"><option value="">请选择年级</option></select>' +
            "</div>" +
            '<div class="tag-dialog-field">' +
            "<label>章/单元 <span class=\"required\">*</span></label>" +
            '<select id="tagDialogMainTag"><option value="">请选择章/单元</option></select>' +
            "</div>" +
            '<div class="tag-dialog-field">' +
            "<label>知识点标签（可多选，隐性属性）</label>" +
            '<div class="tag-dialog-subtags" id="tagDialogSubTags"></div>' +
            "</div>" +
            "</div>" +
            '<div class="tag-dialog-footer">' +
            '<button class="tag-dialog-btn tag-dialog-btn-cancel" id="tagDialogCancel">取消</button>' +
            '<button class="tag-dialog-btn tag-dialog-btn-save" id="tagDialogSave" disabled>保存</button>' +
            "</div>";

        overlay.appendChild(dialog);
        document.body.appendChild(overlay);

        // 点击遮罩关闭
        overlay.addEventListener("click", function (e) {
            if (e.target === overlay) closeDialog();
        });

        // 取消按钮
        document.getElementById("tagDialogCancel").addEventListener("click", closeDialog);

        return dialog;
    }

    /**
     * 填充知识域下拉
     */
    function populateVersions(versions, selected) {
        var sel = document.getElementById("tagDialogVersion");
        if (!sel) return;
        sel.innerHTML = '<option value="">请选择知识域</option>';
        (versions || []).forEach(function (v) {
            var opt = document.createElement("option");
            opt.value = v;
            opt.textContent = v;
            if (v === selected) opt.selected = true;
            sel.appendChild(opt);
        });
    }

    /**
     * 填充年级下拉
     */
    function populateGrades(grades, selected) {
        var sel = document.getElementById("tagDialogGrade");
        if (!sel) return;
        sel.innerHTML = '<option value="">请选择年级</option>';
        var order = ['一上', '一下', '二上', '二下', '三上', '三下', '四上', '四下', '五上', '五下', '六上', '六下', '七上', '七下', '八上', '八下', '九上', '九下'];
        (grades || []).slice().sort(function (a, b) {
            return order.indexOf(a) - order.indexOf(b);
        }).forEach(function (g) {
            var opt = document.createElement("option");
            opt.value = g;
            opt.textContent = g;
            if (g === selected) opt.selected = true;
            sel.appendChild(opt);
        });
    }

    /**
     * 填充章/单元下拉
     */
    function populateMainTags(mainTags, selected) {
        var sel = document.getElementById("tagDialogMainTag");
        if (!sel) return;
        sel.innerHTML = '<option value="">请选择章/单元</option>';
        (mainTags || []).forEach(function (m) {
            var opt = document.createElement("option");
            opt.value = m;
            opt.textContent = m;
            if (m === selected) opt.selected = true;
            sel.appendChild(opt);
        });
    }

    /**
     * 填充子标签多选区
     */
    function populateSubTags(mainTag, hierarchy, version, grade) {
        var container = document.getElementById("tagDialogSubTags");
        if (!container) return;
        container.innerHTML = "";
        selectedSubTags = [];

        if (!mainTag) return;

        // 从 hierarchy 中查找该主标签下的所有子标签
        var subTags = {};
        var hierarchyData = hierarchy || {};

        // 遍历所有版本和年级，收集该主标签的所有子标签
        Object.keys(hierarchyData).forEach(function (ver) {
            var grades = hierarchyData[ver] || {};
            Object.keys(grades).forEach(function (gr) {
                var mains = grades[gr] || {};
                if (mains[mainTag]) {
                    (mains[mainTag] || []).forEach(function (sub) {
                        subTags[sub] = true;
                    });
                }
            });
        });

        // 如果有指定版本和年级，优先使用该组合的子标签
        if (version && grade && hierarchyData[version] && hierarchyData[version][grade] && hierarchyData[version][grade][mainTag]) {
            subTags = {};
            hierarchyData[version][grade][mainTag].forEach(function (sub) {
                subTags[sub] = true;
            });
        }

        Object.keys(subTags).sort().forEach(function (sub) {
            var chip = document.createElement("span");
            chip.className = "tag-dialog-subtag";
            chip.textContent = sub;
            chip.dataset.value = sub;
            chip.addEventListener("click", function () {
                toggleSubTag(sub, chip);
            });
            container.appendChild(chip);
        });
    }

    /**
     * 切换子标签选中状态
     */
    function toggleSubTag(tag, chip) {
        var idx = selectedSubTags.indexOf(tag);
        if (idx >= 0) {
            selectedSubTags.splice(idx, 1);
            chip.classList.remove("selected");
        } else {
            selectedSubTags.push(tag);
            chip.classList.add("selected");
        }
    }

    /**
     * 检查必填项，控制保存按钮状态
     */
    function updateSaveButton() {
        var version = document.getElementById("tagDialogVersion").value;
        var grade = document.getElementById("tagDialogGrade").value;
        var mainTag = document.getElementById("tagDialogMainTag").value;
        var btn = document.getElementById("tagDialogSave");
        if (btn) {
            btn.disabled = !(version && grade && mainTag);
        }
    }

    /**
     * 保存标签
     */
    async function saveTags() {
        var version = document.getElementById("tagDialogVersion").value;
        var grade = document.getElementById("tagDialogGrade").value;
        var mainTag = document.getElementById("tagDialogMainTag").value;

        if (!version || !grade || !mainTag) return;

        var btn = document.getElementById("tagDialogSave");
        if (btn) {
            btn.disabled = true;
            btn.textContent = "保存中...";
        }

        try {
            var apiBase = global.API_BASE || "";
            var resp = await fetch(apiBase + "/api/teachings/" + currentTaskId + "/knowledge-tags", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    version: version,
                    grade: grade,
                    main_tag: mainTag,
                    sub_tags: selectedSubTags,
                    confirmed: true,
                }),
            });

            if (resp.ok) {
                var result = await resp.json();
                closeDialog();
                // 刷新页面以显示新标签
                if (typeof global.onKnowledgeTagsUpdated === "function") {
                    global.onKnowledgeTagsUpdated(result.knowledge_tags);
                } else {
                    location.reload();
                }
            } else {
                var err = await resp.json().catch(function () { return {}; });
                alert("保存失败: " + (err.detail || resp.statusText));
                if (btn) {
                    btn.disabled = false;
                    btn.textContent = "保存";
                }
            }
        } catch (e) {
            alert("保存失败: " + e.message);
            if (btn) {
                btn.disabled = false;
                btn.textContent = "保存";
            }
        }
    }

    /**
     * 关闭弹窗
     */
    function closeDialog() {
        var existing = document.getElementById("tagSelectionDialog");
        if (existing) {
            existing.remove();
        }
    }

    /**
     * 显示弹窗
     * @param {string} taskId - 任务ID
     * @param {Object} existingTags - 已有的标签（可空）
     */
    async function show(taskId, existingTags) {
        currentTaskId = taskId;
        var data = await loadFramework();
        if (!data) {
            alert("无法加载标签框架数据，请稍后重试");
            return;
        }

        createDialog(existingTags || {});
        populateVersions(data.versions, (existingTags && existingTags.version) || "");
        populateGrades(data.grades, (existingTags && existingTags.grade) || "");
        populateMainTags(data.main_tags, (existingTags && existingTags.main_tag) || "");
        populateSubTags(
            (existingTags && existingTags.main_tag) || "",
            data.hierarchy,
            (existingTags && existingTags.version) || "",
            (existingTags && existingTags.grade) || ""
        );

        // 恢复已有子标签的选中状态
        if (existingTags && existingTags.sub_tags) {
            existingTags.sub_tags.forEach(function (sub) {
                var chip = document.querySelector('.tag-dialog-subtag[data-value="' + escapeHtml(sub) + '"]');
                if (chip) {
                    chip.classList.add("selected");
                    if (selectedSubTags.indexOf(sub) < 0) {
                        selectedSubTags.push(sub);
                    }
                }
            });
        }

        updateSaveButton();

        // 绑定事件
        document.getElementById("tagDialogVersion").addEventListener("change", function () {
            updateSaveButton();
            // 联动子标签
            var mainTag = document.getElementById("tagDialogMainTag").value;
            var version = this.value;
            var grade = document.getElementById("tagDialogGrade").value;
            if (mainTag) {
                populateSubTags(mainTag, data.hierarchy, version, grade);
            }
        });

        document.getElementById("tagDialogGrade").addEventListener("change", function () {
            updateSaveButton();
            var mainTag = document.getElementById("tagDialogMainTag").value;
            var version = document.getElementById("tagDialogVersion").value;
            var grade = this.value;
            if (mainTag) {
                populateSubTags(mainTag, data.hierarchy, version, grade);
            }
        });

        document.getElementById("tagDialogMainTag").addEventListener("change", function () {
            updateSaveButton();
            var version = document.getElementById("tagDialogVersion").value;
            var grade = document.getElementById("tagDialogGrade").value;
            populateSubTags(this.value, data.hierarchy, version, grade);
        });

        document.getElementById("tagDialogSave").addEventListener("click", saveTags);
    }

    /**
     * 检查是否需要显示弹窗（旧逻辑：标签缺失时需要手动选择）
     * @param {Object} metadata - 教学内容元数据
     * @returns {boolean} 是否需要手动选择
     */
    function checkNeedsSelection(metadata) {
        if (!metadata) return false;
        // 明确标记需要选择
        if (metadata.needs_tag_selection) return true;
        // 知识点标签缺失或主标签为空
        if (!metadata.knowledge_tags) return true;
        var kt = metadata.knowledge_tags;
        if (!kt.main_tag || !kt.version || !kt.grade) return true;
        return false;
    }

    /**
     * 检查是否需要弹出"确认知识点标签"弹窗
     * 规则：标签尚未被用户确认过（knowledge_tags_confirmed !== true）时返回 true。
     * 已确认的标签不再弹出，实现"仅创建时一次"的确认流程。
     * @param {Object} metadata - 教学内容元数据
     * @returns {boolean} 是否需要弹出确认弹窗
     */
    function needsConfirmation(metadata) {
        if (!metadata) return false;
        // 已确认过，不再弹出
        if (metadata.knowledge_tags_confirmed === true) return false;
        // 尚未确认，需要弹出（无论标签是否已识别，都让用户核对一次）
        return true;
    }

    // 导出
    global.TagSelectionDialog = {
        show: show,
        close: closeDialog,
        checkNeedsSelection: checkNeedsSelection,
        needsConfirmation: needsConfirmation,
    };
})(window);
