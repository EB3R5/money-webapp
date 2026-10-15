/*
 * Native launcher for money.app.
 *
 * Must be a compiled Mach-O (not a shell script): macOS TCC attributes
 * file access to the process's code signature, and a zsh-script bundle
 * gets attributed to /bin/zsh — so the app never receives its own
 * Documents-folder grant and dies with EPERM reading the venv.
 *
 * cds to the repo so the relative .venv path resolves, then execs the
 * shared launcher by path (packaging/ is never imported). The repo path is
 * the MONEY_REPO environment variable, else the MONEY_REPO macro build.sh
 * compiles in from its own location.
 */
#include <unistd.h>
#include <stdlib.h>
#include <stdio.h>
#include <libgen.h>
#include <string.h>
#include <mach-o/dyld.h>

#ifndef MONEY_REPO
#define MONEY_REPO ""
#endif

int main(void) {
    char exe[4096]; uint32_t size = sizeof(exe);
    if (_NSGetExecutablePath(exe, &size) != 0) return 1;
    char macos_dir[4096];
    dirname_r(exe, macos_dir);              /* .../Contents/MacOS */
    char contents[4096];
    dirname_r(macos_dir, contents);         /* .../Contents */
    char icon[4600];
    snprintf(icon, sizeof(icon), "%s/Resources/money.icns", contents);
    setenv("MONEY_APP_ICON", icon, 1);      /* read by packaging/desktop/launcher.py */

    const char *repo = getenv("MONEY_REPO");
    if (repo == NULL || *repo == 0) repo = MONEY_REPO;
    if (*repo == 0) { fputs("money: MONEY_REPO is not set and no path was compiled in\n", stderr); return 1; }
    if (chdir(repo) != 0) { perror("chdir"); return 1; }
    execl(".venv/bin/python", "python", "packaging/desktop/launcher.py", (char *)NULL);
    perror("execl");
    return 1;
}
