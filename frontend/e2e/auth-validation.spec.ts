import { expect, Page, test } from "playwright/test";

const defaultUser = {
  id: "11111111-1111-1111-1111-111111111111",
  email: "learner@example.com",
  username: "learner",
  programming_level: 3,
  maths_level: 3,
  is_admin: false,
  created_at: "2026-01-01T00:00:00Z",
};

interface AuthMockState {
  authenticated: boolean;
  enableUclRegistrationEmailPolicy: boolean;
  loginError: string | null;
  registerSendCodeError: string | null;
  registerError: string | null;
  passwordResetSendCodeError: string | null;
  passwordResetConfirmError: string | null;
  changePasswordError: string | null;
  profileUpdateError: string | null;
  user: typeof defaultUser;
}

const registrationEmailPolicyDetail =
  "Registration is limited to UCL student emails in the format " +
  "name.name.<digits>@ucl.ac.uk. Configured admin emails are exempt.";
const userNoticeAcceptanceDetail =
  "Please accept the Guided Cursor user notice.";
const verificationCodeSendResponse = {
  message: "Verification code sent.",
  resend_cooldown_seconds: 120,
};
const defaultZones = [
  {
    id: "zone-1",
    title: "Python Foundations",
    description: "Starter exercises for the Learning Hub.",
    order: 1,
    created_at: "2026-01-02T00:00:00Z",
    notebook_count: 1,
  },
];

function createAuthMockState(): AuthMockState {
  return {
    authenticated: false,
    enableUclRegistrationEmailPolicy: false,
    loginError: null,
    registerSendCodeError: null,
    registerError: null,
    passwordResetSendCodeError: null,
    passwordResetConfirmError: null,
    changePasswordError: null,
    profileUpdateError: null,
    user: { ...defaultUser },
  };
}

function errorStatus(message: string): number {
  if (message === "Invalid email or password") {
    return 401;
  }
  if (message === "Email is not registered.") {
    return 404;
  }
  return 400;
}

async function installAuthApiMocks(
  page: Page,
  state: AuthMockState
): Promise<void> {
  await page.route("**/api/**", async (route) => {
    const request = route.request();
    const resourceType = request.resourceType();
    const url = new URL(request.url());
    const path = url.pathname;
    const method = request.method();

    if ((resourceType !== "fetch" && resourceType !== "xhr") || !path.startsWith("/api/")) {
      await route.fallback();
      return;
    }

    const respondJson = async (payload: unknown, status = 200) => {
      await route.fulfill({
        status,
        contentType: "application/json",
        body: JSON.stringify(payload),
      });
    };

    const respondError = async (message: string) => {
      await respondJson({ detail: message }, errorStatus(message));
    };

    if (path === "/api/auth/register/policy" && method === "GET") {
      await respondJson({
        enable_ucl_registration_email_policy: state.enableUclRegistrationEmailPolicy,
      });
      return;
    }

    if (path === "/api/auth/refresh" && method === "POST") {
      if (!state.authenticated) {
        await respondError("Refresh token not found");
        return;
      }
      await respondJson({ access_token: "playwright-access-token", token_type: "bearer" });
      return;
    }

    if (path === "/api/auth/me" && method === "GET") {
      if (!state.authenticated) {
        await respondError("User not found");
        return;
      }
      await respondJson(state.user);
      return;
    }

    if (path === "/api/auth/login" && method === "POST") {
      if (state.loginError) {
        await respondError(state.loginError);
        return;
      }
      state.authenticated = true;
      await respondJson({ access_token: "login-token", token_type: "bearer" });
      return;
    }

    if (path === "/api/auth/logout" && method === "POST") {
      state.authenticated = false;
      await respondJson({ message: "Logged out successfully." });
      return;
    }

    if (path === "/api/auth/register/send-code" && method === "POST") {
      if (state.registerSendCodeError) {
        await respondError(state.registerSendCodeError);
        return;
      }
      await respondJson(verificationCodeSendResponse);
      return;
    }

    if (path === "/api/auth/register" && method === "POST") {
      if (state.registerError) {
        await respondError(state.registerError);
        return;
      }
      const body = request.postDataJSON() as {
        email: string;
        username: string;
        programming_level?: number;
        maths_level?: number;
      };
      state.authenticated = true;
      state.user = {
        ...state.user,
        email: body.email,
        username: body.username,
        programming_level: body.programming_level ?? state.user.programming_level,
        maths_level: body.maths_level ?? state.user.maths_level,
      };
      await respondJson({ access_token: "register-token", token_type: "bearer" });
      return;
    }

    if (path === "/api/auth/password-reset/send-code" && method === "POST") {
      if (state.passwordResetSendCodeError) {
        await respondError(state.passwordResetSendCodeError);
        return;
      }
      await respondJson(verificationCodeSendResponse);
      return;
    }

    if (path === "/api/auth/password-reset/confirm" && method === "POST") {
      if (state.passwordResetConfirmError) {
        await respondError(state.passwordResetConfirmError);
        return;
      }
      await respondJson({ message: "Password reset successfully." });
      return;
    }

    if (path === "/api/auth/me/password" && method === "PUT") {
      if (state.changePasswordError) {
        await respondError(state.changePasswordError);
        return;
      }
      await respondJson({ message: "Password reset successfully." });
      return;
    }

    if (path === "/api/auth/me" && method === "PUT") {
      if (state.profileUpdateError) {
        await respondError(state.profileUpdateError);
        return;
      }
      const body = request.postDataJSON() as {
        username?: string;
        programming_level?: number;
        maths_level?: number;
      };
      state.user = {
        ...state.user,
        username: body.username ?? state.user.username,
        programming_level: body.programming_level ?? state.user.programming_level,
        maths_level: body.maths_level ?? state.user.maths_level,
      };
      await respondJson(state.user);
      return;
    }

    if (path === "/api/auth/me" && method === "DELETE") {
      state.authenticated = false;
      await respondJson({ message: "Account deleted successfully." });
      return;
    }

    if (path === "/api/chat/usage" && method === "GET") {
      await respondJson({
        week_start: "2026-03-02",
        week_end: "2026-03-08",
        input_tokens_used: 1200,
        output_tokens_used: 800,
        weighted_tokens_used: 2000,
        remaining_weighted_tokens: 8000,
        weekly_weighted_limit: 10000,
        usage_percentage: 20,
      });
      return;
    }

    if (path === "/api/zones" && method === "GET") {
      await respondJson(defaultZones);
      return;
    }

    await respondJson({});
  });
}

async function expectInvalidField(
  page: Page,
  selector: string,
  errorSelector: string,
  message: string
): Promise<void> {
  await expect(page.locator(selector)).toHaveClass(/border-red-300/);
  await expect(page.locator(errorSelector)).toHaveText(message);
}

async function submitLogin(
  page: Page,
  credentials: { email?: string; password?: string } = {}
): Promise<void> {
  await page.locator("#email").fill(credentials.email ?? "learner@example.com");
  await page.locator("#password").fill(credentials.password ?? "StrongPass123");
  await page.getByRole("button", { name: "Login" }).click();
}

async function submitRegistration(
  page: Page,
  values: {
    email?: string;
    verificationCode?: string;
    username?: string;
    password?: string;
  } = {}
): Promise<void> {
  const password = values.password ?? "StrongPass123";

  await page.locator("#email").fill(values.email ?? "learner@example.com");
  await page
    .locator("#verificationCode")
    .fill(values.verificationCode ?? "123456");
  await page.locator("#username").fill(values.username ?? "new_user");
  await page.locator("#password").fill(password);
  await page.locator("#confirmPassword").fill(password);
  await page.locator("#acceptedUserNotice").check();
  await page.getByRole("button", { name: "Create Account" }).click();
}

test.describe("Auth and profile validation", () => {
  test("login validates on blur and clears once the email is corrected", async ({
    page,
  }) => {
    const state = createAuthMockState();
    await installAuthApiMocks(page, state);

    await page.goto("/login");

    const email = page.locator("#email");
    await email.focus();
    await email.blur();

    await expectInvalidField(
      page,
      "#email",
      "#login-email-error",
      "Please enter your email first."
    );

    await email.fill("learner@example.com");

    await expect(page.locator("#email")).not.toHaveClass(/border-red-300/);
    await expect(page.locator("#login-email-error")).toHaveCount(0);
  });

  test("login maps invalid credentials to both fields", async ({ page }) => {
    const state = createAuthMockState();
    state.loginError = "Invalid email or password";
    await installAuthApiMocks(page, state);

    await page.goto("/login");
    await page.locator("#email").fill("learner@example.com");
    await page.locator("#password").fill("wrong-password");
    await page.getByRole("button", { name: "Login" }).click();

    await expectInvalidField(
      page,
      "#email",
      "#login-email-error",
      "Invalid email or password"
    );
    await expectInvalidField(
      page,
      "#password",
      "#login-password-error",
      "Invalid email or password"
    );
  });

  test("login redirects to Learning Hub when there is no saved destination", async ({
    page,
  }) => {
    const state = createAuthMockState();
    await installAuthApiMocks(page, state);

    await page.goto("/login");
    await submitLogin(page);

    await expect(page).toHaveURL(/\/learning-hub$/);
    await expect(page.getByRole("heading", { name: "Learning Hub" })).toBeVisible();
    await expect(page.getByText("Python Foundations")).toBeVisible();
  });

  test("visiting login while authenticated automatically logs the user out", async ({
    page,
  }) => {
    const state = createAuthMockState();
    state.authenticated = true;
    await installAuthApiMocks(page, state);

    await page.goto("/login");

    await expect(page).toHaveURL(/\/login$/);
    await expect(page.getByRole("heading", { name: "Login" })).toBeVisible();

    await page.goto("/profile");
    await expect(page).toHaveURL(/\/login$/);
  });

  test("login returns to the original protected page before falling back to Learning Hub", async ({
    page,
  }) => {
    const state = createAuthMockState();
    await installAuthApiMocks(page, state);

    await page.goto("/profile");
    await expect(page).toHaveURL(/\/login$/);

    await submitLogin(page);

    await expect(page).toHaveURL(/\/profile$/);
    await expect(page.locator("#username")).toHaveValue(state.user.username);
  });

  test("register highlights the email field when the email format is invalid", async ({
    page,
  }) => {
    const state = createAuthMockState();
    await installAuthApiMocks(page, state);

    await page.goto("/register");
    await page.locator("#email").fill("learner-at-example.com");
    await page.getByRole("button", { name: "Send code" }).click();

    await expectInvalidField(
      page,
      "#email",
      "#register-email-error",
      "Please enter a valid email address."
    );
  });

  test("register highlights the email field when the UCL policy blocks the address", async ({
    page,
  }) => {
    const state = createAuthMockState();
    state.enableUclRegistrationEmailPolicy = true;
    await installAuthApiMocks(page, state);

    await page.goto("/register");
    await page.locator("#email").fill("learner@example.com");
    await page.locator("#username").fill("new_learner");
    await page.getByRole("button", { name: "Send code" }).click();

    await expectInvalidField(
      page,
      "#email",
      "#register-email-error",
      registrationEmailPolicyDetail
    );
  });

  test("register maps duplicate usernames to the username field", async ({
    page,
  }) => {
    const state = createAuthMockState();
    state.registerError = "Username already taken";
    await installAuthApiMocks(page, state);

    await page.goto("/register");
    await page.locator("#email").fill("learner@example.com");
    await page.locator("#verificationCode").fill("123456");
    await page.locator("#username").fill("taken_name");
    await page.locator("#password").fill("StrongPass123");
    await page.locator("#confirmPassword").fill("StrongPass123");
    await page.locator("#acceptedUserNotice").check();
    await page.getByRole("button", { name: "Create Account" }).click();

    await expectInvalidField(
      page,
      "#username",
      "#register-username-error",
      "Username already taken"
    );
  });

  test("register redirects to Learning Hub when there is no saved destination", async ({
    page,
  }) => {
    const state = createAuthMockState();
    await installAuthApiMocks(page, state);

    await page.goto("/register");
    await submitRegistration(page);

    await expect(page).toHaveURL(/\/learning-hub$/);
    await expect(page.getByRole("heading", { name: "Learning Hub" })).toBeVisible();
    await expect(page.getByText("Python Foundations")).toBeVisible();
  });

  test("visiting register while authenticated automatically logs the user out", async ({
    page,
  }) => {
    const state = createAuthMockState();
    state.authenticated = true;
    await installAuthApiMocks(page, state);

    await page.goto("/register");

    await expect(page).toHaveURL(/\/register$/);
    await expect(page.getByText("Tell us about you")).toBeVisible();

    await page.goto("/profile");
    await expect(page).toHaveURL(/\/login$/);
  });

  test("register preserves the original protected page when coming from the login redirect state", async ({
    page,
  }) => {
    const state = createAuthMockState();
    await installAuthApiMocks(page, state);

    await page.goto("/profile");
    await expect(page).toHaveURL(/\/login$/);

    await page.getByRole("link", { name: "Register" }).click();
    await expect(page).toHaveURL(/\/register$/);

    await submitRegistration(page, { username: "redirected_user" });

    await expect(page).toHaveURL(/\/profile$/);
    await expect(page.locator("#username")).toHaveValue("redirected_user");
  });

  test("register shows a two-minute resend countdown after sending a code", async ({
    page,
  }) => {
    const state = createAuthMockState();
    await installAuthApiMocks(page, state);

    await page.goto("/register");
    await page.locator("#email").fill("learner@example.com");
    await page.locator("#username").fill("new_learner");
    await page.getByRole("button", { name: "Send code" }).click();

    await expect(
      page.getByRole("button", { name: "Resend in 120s" })
    ).toBeDisabled();
  });

  test("register requires accepting the user notice before account creation", async ({
    page,
  }) => {
    const state = createAuthMockState();
    await installAuthApiMocks(page, state);

    await page.goto("/register");
    await page.locator("#email").fill("learner@example.com");
    await page.locator("#verificationCode").fill("123456");
    await page.locator("#username").fill("new_user");
    await page.locator("#password").fill("StrongPass123");
    await page.locator("#confirmPassword").fill("StrongPass123");
    await page.getByRole("button", { name: "Create Account" }).click();

    await expect(page.locator("#acceptedUserNotice")).not.toBeChecked();
    await expect(
      page.locator("#register-acceptedUserNotice-error")
    ).toHaveText(userNoticeAcceptanceDetail);
  });

  test("register opens the user notice dialog on demand", async ({ page }) => {
    const state = createAuthMockState();
    await installAuthApiMocks(page, state);

    await page.goto("/register");
    await page.getByRole("button", { name: "User Notice" }).click();

    await expect(page.getByRole("dialog")).toBeVisible();
    await expect(page.getByText("Welcome to Guided Cursor")).toBeVisible();
    await page.getByRole("button", { name: "Close" }).click();
    await expect(page.getByRole("dialog")).toHaveCount(0);
  });

  test("forgot-password maps unknown emails back to the email field", async ({
    page,
  }) => {
    const state = createAuthMockState();
    state.passwordResetSendCodeError = "Email is not registered.";
    await installAuthApiMocks(page, state);

    await page.goto("/forgot-password");
    await page.locator("#email").fill("missing@example.com");
    await page.getByRole("button", { name: "Send code" }).click();

    await expectInvalidField(
      page,
      "#email",
      "#forgot-password-email-error",
      "Email is not registered."
    );
  });

  test("visiting forgot-password while authenticated automatically logs the user out", async ({
    page,
  }) => {
    const state = createAuthMockState();
    state.authenticated = true;
    await installAuthApiMocks(page, state);

    await page.goto("/forgot-password");

    await expect(page).toHaveURL(/\/forgot-password$/);
    await expect(page.getByRole("heading", { name: "Forgot Password" })).toBeVisible();

    await page.goto("/profile");
    await expect(page).toHaveURL(/\/login$/);
  });

  test("forgot-password shows a two-minute resend countdown after sending a code", async ({
    page,
  }) => {
    const state = createAuthMockState();
    await installAuthApiMocks(page, state);

    await page.goto("/forgot-password");
    await page.locator("#email").fill("learner@example.com");
    await page.getByRole("button", { name: "Send code" }).click();

    await expect(
      page.getByRole("button", { name: "Resend in 120s" })
    ).toBeDisabled();
  });

  test("signed-in email reset maps invalid codes to the verification field", async ({
    page,
  }) => {
    const state = createAuthMockState();
    state.authenticated = true;
    state.passwordResetConfirmError = "Invalid or expired verification code";
    await installAuthApiMocks(page, state);

    await page.goto("/profile/reset-password/email");
    await page.locator("#verificationCode").fill("123456");
    await page.locator("#newPassword").fill("StrongPass123");
    await page.locator("#confirmNewPassword").fill("StrongPass123");
    await page.getByRole("button", { name: "Reset Password" }).click();

    await expectInvalidField(
      page,
      "#verificationCode",
      "#reset-email-verificationCode-error",
      "Invalid or expired verification code"
    );
  });

  test("signed-in email reset shows a two-minute resend countdown after sending a code", async ({
    page,
  }) => {
    const state = createAuthMockState();
    state.authenticated = true;
    await installAuthApiMocks(page, state);

    await page.goto("/profile/reset-password/email");
    await page.getByRole("button", { name: "Send code" }).click();

    await expect(
      page.getByRole("button", { name: "Resend in 120s" })
    ).toBeDisabled();
  });

  test("signed-in password reset maps wrong current passwords to the current-password field", async ({
    page,
  }) => {
    const state = createAuthMockState();
    state.authenticated = true;
    state.changePasswordError = "Current password is incorrect.";
    await installAuthApiMocks(page, state);

    await page.goto("/profile/reset-password/password");
    await page.locator("#currentPassword").fill("WrongPass123");
    await page.locator("#newPassword").fill("StrongPass123");
    await page.locator("#confirmNewPassword").fill("StrongPass123");
    await page.getByRole("button", { name: "Reset Password" }).click();

    await expectInvalidField(
      page,
      "#currentPassword",
      "#reset-password-currentPassword-error",
      "Current password is incorrect."
    );
  });

  test("profile maps duplicate usernames to the username field", async ({
    page,
  }) => {
    const state = createAuthMockState();
    state.authenticated = true;
    state.profileUpdateError = "Username already taken";
    await installAuthApiMocks(page, state);

    await page.goto("/profile");
    await page.locator("#username").fill("taken_name");
    await page.getByRole("button", { name: "Save Changes" }).click();

    await expectInvalidField(
      page,
      "#username",
      "#profile-username-error",
      "Username already taken"
    );
  });

  test("profile deletes the account after confirmation and redirects to register", async ({
    page,
  }) => {
    const state = createAuthMockState();
    state.authenticated = true;
    await installAuthApiMocks(page, state);

    page.once("dialog", async (dialog) => {
      expect(dialog.message()).toContain("permanently removes");
      await dialog.accept();
    });

    await page.goto("/profile");
    await expect(
      page.getByText(
        "Deleting your account permanently removes your profile, chats, uploads, personal notebooks, and Learning Hub progress."
      )
    ).toBeVisible();

    await page.getByRole("button", { name: "Delete Account" }).click();
    await expect(page).toHaveURL(/\/register$/);
  });

  test("root path redirects unauthenticated users to login", async ({ page }) => {
    const state = createAuthMockState();
    await installAuthApiMocks(page, state);

    await page.goto("/");

    await expect(page).toHaveURL(/\/login$/);
  });

  test("root path redirects authenticated users to Learning Hub", async ({
    page,
  }) => {
    const state = createAuthMockState();
    state.authenticated = true;
    await installAuthApiMocks(page, state);

    await page.goto("/");

    await expect(page).toHaveURL(/\/learning-hub$/);
    await expect(page.getByText("Python Foundations")).toBeVisible();
  });
});
