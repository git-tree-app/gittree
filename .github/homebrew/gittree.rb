# Homebrew cask template for GitTree (the installed app is "Git Tree").
#
# This file is a template kept in the public release repository. It is not read by
# Homebrew from here. To publish it, copy it unchanged to `Casks/gittree.rb` in the
# `git-tree-app/homebrew-tap` repository; users then install with:
#
#   brew install --cask git-tree-app/tap/gittree
#
# The URL is the stable asset name from RELEASING.md ("Release asset contract"):
# GitHub redirects `releases/latest/download/Git-Tree-macOS.dmg` to the universal,
# Developer ID signed and Apple notarized `.dmg` of the newest stable release.
# Because that name never changes, the cask uses `version :latest` and
# `sha256 :no_check`; integrity is checked by Gatekeeper (notarization) and the
# release's `SHA256SUMS.txt`. The app then updates itself (`auto_updates true`).
cask "gittree" do
  version :latest
  sha256 :no_check

  url "https://github.com/git-tree-app/gittree/releases/latest/download/Git-Tree-macOS.dmg",
      verified: "github.com/git-tree-app/gittree/"
  name "GitTree"
  name "Git Tree"
  desc "Local-first visual Git client for macOS, Windows and Linux"
  homepage "https://gittree.app/"

  auto_updates true
  depends_on macos: ">= :ventura"

  app "Git Tree.app"

  zap trash: [
    "~/Library/Application Support/com.eslamfaisal.opengittree",
    "~/Library/Caches/com.eslamfaisal.opengittree",
    "~/Library/HTTPStorages/com.eslamfaisal.opengittree",
    "~/Library/Logs/com.eslamfaisal.opengittree",
    "~/Library/Preferences/com.eslamfaisal.opengittree.plist",
    "~/Library/Saved Application State/com.eslamfaisal.opengittree.savedState",
    "~/Library/WebKit/com.eslamfaisal.opengittree",
  ]
end
