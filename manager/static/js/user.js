/* 用户WebUI JavaScript */

// API基础URL
const API_BASE = '/api';

// 自动关闭提示框
document.addEventListener('DOMContentLoaded', function() {
    const alerts = document.querySelectorAll('.alert.alert-dismissible');
    alerts.forEach(function(alert) {
        setTimeout(function() {
            new bootstrap.Alert(alert).close();
        }, 5000);
    });
});

// 通用API调用函数
async function apiCall(endpoint, method = 'GET', data = null) {
    const options = {
        method: method,
        headers: {
            'Content-Type': 'application/json',
        }
    };

    if (data) {
        options.body = JSON.stringify(data);
    }

    try {
        const response = await fetch(API_BASE + endpoint, options);
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }
        return await response.json();
    } catch (error) {
        console.error('API Error:', error);
        throw error;
    }
}

// 格式化金币数字
function formatCoin(amount) {
    if (amount >= 1000000) {
        return (amount / 1000000).toFixed(1) + 'M';
    }
    if (amount >= 1000) {
        return (amount / 1000).toFixed(1) + 'K';
    }
    return amount.toString();
}

// 格式化时间
function formatTime(date) {
    if (typeof date === 'string') {
        date = new Date(date);
    }
    return date.toLocaleString('zh-CN');
}

// 显示加载状态
function showLoading(element) {
    element.innerHTML = '<div class="text-center"><i class="fas fa-spinner fa-spin"></i> 加载中...</div>';
}

// 显示错误信息
function showError(element, message) {
    element.innerHTML = `<div class="alert alert-danger"><i class="fas fa-exclamation-circle me-2"></i>${message}</div>`;
}

// 显示空状态
function showEmpty(element, message = '暂无数据') {
    element.innerHTML = `<div class="text-center text-muted py-5"><i class="fas fa-inbox me-2"></i>${message}</div>`;
}

// 复制到剪贴板
function copyToClipboard(text) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(() => {
            showToast('已复制到剪贴板');
        }).catch(() => {
            fallbackCopy(text);
        });
    } else {
        fallbackCopy(text);
    }
}

function fallbackCopy(text) {
    const textarea = document.createElement('textarea');
    textarea.value = text;
    document.body.appendChild(textarea);
    textarea.select();
    document.execCommand('copy');
    document.body.removeChild(textarea);
    showToast('已复制到剪贴板');
}

// 显示Toast通知
function showToast(message, type = 'success') {
    const toastContainer = document.querySelector('.toast-container');
    const toastHtml = `
        <div class="toast" role="alert">
            <div class="toast-body bg-${type} text-white">
                ${message}
            </div>
        </div>
    `;
    if (!toastContainer) {
        const container = document.createElement('div');
        container.className = 'toast-container position-fixed bottom-0 end-0 p-3';
        document.body.appendChild(container);
        container.innerHTML = toastHtml;
    }
}

// 确认对话框
function confirmAction(message) {
    return confirm(message);
}

// 获取查询参数
function getQueryParam(name) {
    const params = new URLSearchParams(window.location.search);
    return params.get(name);
}

// 数字输入验证
function validateNumber(value, min = 1, max = Infinity) {
    const num = parseInt(value);
    return !isNaN(num) && num >= min && num <= max;
}

// 文本输入验证
function validateText(value, minLength = 1, maxLength = 100) {
    return value.length >= minLength && value.length <= maxLength;
}

// 金币不足提示
function showInsufficientFunds() {
    showToast('金币不足，无法完成此操作', 'danger');
}

// 导出为CSV
function exportToCSV(data, filename = 'export.csv') {
    const csv = convertToCSV(data);
    const link = document.createElement('a');
    link.setAttribute('href', 'data:text/csv;charset=utf-8,' + encodeURIComponent(csv));
    link.setAttribute('download', filename);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
}

function convertToCSV(data) {
    if (!Array.isArray(data) || data.length === 0) return '';
    
    const headers = Object.keys(data[0]);
    const csv = [headers.join(',')];
    
    data.forEach(row => {
        const values = headers.map(header => {
            const value = row[header];
            if (typeof value === 'string') {
                return '"' + value.replace(/"/g, '""') + '"';
            }
            return value;
        });
        csv.push(values.join(','));
    });
    
    return csv.join('\n');
}

// 分页处理
class Pagination {
    constructor(container, perPage = 10) {
        this.container = container;
        this.perPage = perPage;
        this.currentPage = 1;
        this.totalPages = 1;
        this.data = [];
    }

    setData(data) {
        this.data = data;
        this.totalPages = Math.ceil(data.length / this.perPage);
        this.render();
    }

    goToPage(page) {
        if (page < 1 || page > this.totalPages) return;
        this.currentPage = page;
        this.render();
    }

    getPaginatedData() {
        const start = (this.currentPage - 1) * this.perPage;
        return this.data.slice(start, start + this.perPage);
    }

    render() {
        // 实现分页渲染逻辑
    }
}

// 搜索和过滤
class SearchFilter {
    constructor(items, searchField) {
        this.items = items;
        this.searchField = searchField;
        this.filteredItems = items;
    }

    search(query) {
        if (!query) {
            this.filteredItems = this.items;
            return this.filteredItems;
        }

        this.filteredItems = this.items.filter(item => {
            const value = item[this.searchField];
            return value && value.toString().toLowerCase().includes(query.toLowerCase());
        });
        return this.filteredItems;
    }

    filter(key, value) {
        if (!value) {
            this.filteredItems = this.items;
            return this.filteredItems;
        }

        this.filteredItems = this.items.filter(item => item[key] === value);
        return this.filteredItems;
    }
}

export { apiCall, formatCoin, formatTime, Pagination, SearchFilter };
