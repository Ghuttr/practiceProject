function validateForm(form) {
    const password = form.password.value;
    // Проверка длины пароля
    if (password.length < 6) {
        alert("Пароль должен содержать не менее 6 символов.");
        return false; // Отменяем отправку формы
    }
    return true;
}