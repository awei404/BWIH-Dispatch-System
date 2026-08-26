// 调度系统前端逻辑

document.addEventListener('DOMContentLoaded', function() {
    initDatePicker();
    initConfirmations();
});

function initDatePicker() {
    const dateInputs = document.querySelectorAll('input[type="date"]');
    dateInputs.forEach(input => {
        if (!input.value) {
            input.value = new Date().toISOString().split('T')[0];
        }
    });
}

function initConfirmations() {
    const dangerButtons = document.querySelectorAll('[data-confirm]');
    dangerButtons.forEach(btn => {
        btn.addEventListener('click', function(e) {
            if (!confirm(this.dataset.confirm)) {
                e.preventDefault();
            }
        });
    });
}

async function quickCheckin(dmsTaskId, dock, truck) {
    const response = await fetch(`/api/tasks/${dmsTaskId}/checkin`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ dock, actual_truck: truck })
    });
    if (response.ok) {
        location.reload();
    } else {
        alert('Check-in 失败');
    }
}

async function refreshDriverScore(driverId) {
    const response = await fetch(`/api/drivers/${driverId}/score`);
    if (response.ok) {
        const data = await response.json();
        console.log('Score refreshed:', data);
    }
}
