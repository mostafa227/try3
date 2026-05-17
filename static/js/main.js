// Theme Toggle
(function() {
    const themeToggle = document.getElementById('theme-toggle');
    const savedTheme = localStorage.getItem('theme') || 'dark';
    document.documentElement.setAttribute('data-theme', savedTheme);
    if (themeToggle) {
        themeToggle.textContent = savedTheme === 'dark' ? '☀️' : '🌙';
        themeToggle.addEventListener('click', () => {
            const current = document.documentElement.getAttribute('data-theme');
            const next = current === 'dark' ? 'light' : 'dark';
            document.documentElement.setAttribute('data-theme', next);
            localStorage.setItem('theme', next);
            themeToggle.textContent = next === 'dark' ? '☀️' : '🌙';
        });
    }
})();

// Mobile Menu Toggle
const menuBtn = document.querySelector('.mobile-menu-btn');
const navLinks = document.querySelector('.nav-links');
if (menuBtn && navLinks) {
    menuBtn.addEventListener('click', () => {
        navLinks.classList.toggle('active');
    });
}

// Intersection Observer Animations
const observer = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
        if (entry.isIntersecting) {
            entry.target.classList.add('fade-up');
            observer.unobserve(entry.target);
        }
    });
}, { threshold: 0.1 });

document.querySelectorAll('.step-card, .feature-card, .about-card').forEach(el => {
    el.style.opacity = '0';
    observer.observe(el);
});

// Clipboard Paste Button (global)
document.querySelectorAll('.paste-btn').forEach(btn => {
    btn.addEventListener('click', async (e) => {
        const input = e.target.closest('.input-group')?.querySelector('input');
        if (!input) return;
        try {
            const text = await navigator.clipboard.readText();
            input.value = text;
        } catch (err) {
            alert('Unable to access clipboard. Please paste manually.');
        }
    });
});

// Form validation for homepage
const downloadForm = document.getElementById('download-form');
if (downloadForm) {
    downloadForm.addEventListener('submit', (e) => {
        const urlInput = document.getElementById('url-input');
        if (!urlInput.value.trim()) {
            e.preventDefault();
            alert('Please enter a valid URL');
        }
    });
}