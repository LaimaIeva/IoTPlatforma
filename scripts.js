function toggleMenu() {
    const menu = document.getElementById('menu-container');
    const menuToggle = document.getElementById('menu-toggle');
    if (menu.style.right === '0px') {
        menu.style.right = '-250px';
        menuToggle.style.right = '20px';
    } else {
        menu.style.right = '0';
        menuToggle.style.right = '270px';
    }
}

function toggleMode() {
    const body = document.body;
    const modeSlider = document.getElementById('mode-slider');
    if (modeSlider.value === '1') {
        // Dark mode
        body.style.backgroundColor = '#333';
        localStorage.setItem('darkMode', '1');
    } else {
        // Light mode
        body.style.backgroundColor = '#f2f2f2';
        localStorage.setItem('darkMode', '0');
    }
}

document.addEventListener('DOMContentLoaded', function () {
    const storedMode = localStorage.getItem('darkMode');
    const modeSlider = document.getElementById('mode-slider');
    const body = document.body;
    if (storedMode === '1') {
        // Dark mode
        body.style.backgroundColor = '#333';
        modeSlider.value = '1';
    } else {
        // Light mode
        body.style.backgroundColor = '#f2f2f2';
        modeSlider.value = '0';
    }
});
