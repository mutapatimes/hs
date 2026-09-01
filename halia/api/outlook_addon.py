"""Halia inside the Outlook compose window.

An Outlook add-in is a task pane: HTML we host, which Outlook loads in an iframe beside the
message being written. That has two consequences this module exists to handle.

* **It must be served from our own origin.** The pane calls /v1/extension/* directly, and because
  it is served from the same host as the API those calls are same-origin. The CORS allow-list in
  app.py stays untouched, which is the whole reason to host the pane here rather than anywhere
  else. If a future change moves the pane off this origin, every POST it makes will start failing
  preflight.
* **It must opt out of the site-wide framing block.** `_security_headers_mw` puts
  `frame-ancestors 'none'` on any response that does not set its own CSP, which would render the
  pane blank inside Outlook. Each HTML route below sets its own, naming Outlook's hosts — the same
  escape hatch the embedded Shopify app uses.

Distribution needs no review by anyone: an associate sideloads the manifest, or the boutique's IT
administrator deploys it to everyone from the Microsoft 365 admin centre. See
docs/outlook-add-in.md.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import HTTPException
from fastapi.responses import HTMLResponse, Response

from halia import config

_DIR = Path(__file__).resolve().parent.parent.parent / "web" / "addons" / "outlook"

# Where Outlook may frame us from: the web clients, the new Outlook on Windows (which is the web
# client in a shell), the consumer host, and the pre-release ring merchants are sometimes on.
_FRAME_ANCESTORS = " ".join([
    "https://outlook.office.com",
    "https://outlook.office365.com",
    "https://outlook.live.com",
    "https://outlook-sdf.office.com",
    "https://outlook-sdf.office365.com",
    "https://*.microsoft365.com",
])


def _base() -> str:
    """The origin the manifest points at. Everything in an Outlook manifest must be https and on
    one declared domain, so dev, staging and production each serve their own manifest."""
    return (config.HALIA_APP_URL or "https://haliascore.com").rstrip("/")


def _framed(html: str) -> HTMLResponse:
    """An HTML response Outlook is allowed to frame. Setting our own CSP also stops the middleware
    adding X-Frame-Options: DENY, which no CSP can override."""
    return HTMLResponse(html, headers={
        "Content-Security-Policy": f"frame-ancestors {_FRAME_ANCESTORS};",
        "Cache-Control": "no-store",
    })


# The add-in-only XML manifest, not the unified JSON one. The JSON manifest does not support
# Outlook on Mac, and boutiques run Macs. XML works on the web, on Windows (classic and new) and
# on Mac, which is every client that can run a compose task pane.
#
# Mobile is deliberately absent: Outlook on iOS and Android support read-mode add-ins only, so
# there is no compose surface to declare. Saying otherwise in the manifest would promise a pane
# that never appears.
_MANIFEST = """<?xml version="1.0" encoding="UTF-8"?>
<OfficeApp xmlns="http://schemas.microsoft.com/office/appforoffice/1.1"
           xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
           xmlns:bt="http://schemas.microsoft.com/office/officeappbasictypes/1.0"
           xsi:type="MailApp">
  <Id>{addin_id}</Id>
  <Version>1.0.0.0</Version>
  <ProviderName>Halia</ProviderName>
  <DefaultLocale>en-GB</DefaultLocale>
  <DisplayName DefaultValue="Halia"/>
  <Description DefaultValue="Your client book, in the message you are already writing."/>
  <IconUrl DefaultValue="{base}/addons/outlook/asset/icon-64.png"/>
  <HighResolutionIconUrl DefaultValue="{base}/addons/outlook/asset/icon-128.png"/>
  <SupportUrl DefaultValue="{base}/contact"/>
  <AppDomains>
    <AppDomain>{base}</AppDomain>
  </AppDomains>
  <Hosts>
    <Host Name="Mailbox"/>
  </Hosts>
  <Requirements>
    <Sets>
      <Set Name="Mailbox" MinVersion="1.3"/>
    </Sets>
  </Requirements>
  <FormSettings>
    <Form xsi:type="ItemRead">
      <DesktopSettings>
        <SourceLocation DefaultValue="{base}/addons/outlook/taskpane"/>
        <RequestedHeight>420</RequestedHeight>
      </DesktopSettings>
    </Form>
    <Form xsi:type="ItemEdit">
      <DesktopSettings>
        <SourceLocation DefaultValue="{base}/addons/outlook/taskpane"/>
      </DesktopSettings>
    </Form>
  </FormSettings>
  <!-- Reading a recipient needs ReadItem; putting text into the body needs ReadWriteItem,
       which covers both. -->
  <Permissions>ReadWriteItem</Permissions>
  <!-- Where the add-in may appear. A mail manifest is rejected without this. -->
  <Rule xsi:type="RuleCollection" Mode="Or">
    <Rule xsi:type="ItemIs" ItemType="Message" FormType="Read"/>
    <Rule xsi:type="ItemIs" ItemType="Message" FormType="Edit"/>
  </Rule>
  <VersionOverrides xmlns="http://schemas.microsoft.com/office/mailappversionoverrides"
                    xsi:type="VersionOverridesV1_0">
    <Requirements>
      <bt:Sets DefaultMinVersion="1.3">
        <bt:Set Name="Mailbox"/>
      </bt:Sets>
    </Requirements>
    <Hosts>
      <Host xsi:type="MailHost">
        <DesktopFormFactor>
          <FunctionFile resid="functionFile"/>
          <ExtensionPoint xsi:type="MessageComposeCommandSurface">
            <OfficeTab id="TabDefault">
              <Group id="haliaGroup">
                <Label resid="groupLabel"/>
                <Control xsi:type="Button" id="haliaOpen">
                  <Label resid="buttonLabel"/>
                  <Supertip>
                    <Title resid="buttonLabel"/>
                    <Description resid="buttonTip"/>
                  </Supertip>
                  <Icon>
                    <bt:Image size="16" resid="icon16"/>
                    <bt:Image size="32" resid="icon32"/>
                    <bt:Image size="80" resid="icon80"/>
                  </Icon>
                  <Action xsi:type="ShowTaskpane">
                    <SourceLocation resid="taskpane"/>
                  </Action>
                </Control>
              </Group>
            </OfficeTab>
          </ExtensionPoint>
          <ExtensionPoint xsi:type="MessageReadCommandSurface">
            <OfficeTab id="TabDefault">
              <Group id="haliaGroupRead">
                <Label resid="groupLabel"/>
                <Control xsi:type="Button" id="haliaOpenRead">
                  <Label resid="buttonLabel"/>
                  <Supertip>
                    <Title resid="buttonLabel"/>
                    <Description resid="buttonTip"/>
                  </Supertip>
                  <Icon>
                    <bt:Image size="16" resid="icon16"/>
                    <bt:Image size="32" resid="icon32"/>
                    <bt:Image size="80" resid="icon80"/>
                  </Icon>
                  <Action xsi:type="ShowTaskpane">
                    <SourceLocation resid="taskpane"/>
                  </Action>
                </Control>
              </Group>
            </OfficeTab>
          </ExtensionPoint>
        </DesktopFormFactor>
      </Host>
    </Hosts>
    <Resources>
      <bt:Images>
        <bt:Image id="icon16" DefaultValue="{base}/addons/outlook/asset/icon-16.png"/>
        <bt:Image id="icon32" DefaultValue="{base}/addons/outlook/asset/icon-32.png"/>
        <bt:Image id="icon80" DefaultValue="{base}/addons/outlook/asset/icon-80.png"/>
      </bt:Images>
      <bt:Urls>
        <bt:Url id="taskpane" DefaultValue="{base}/addons/outlook/taskpane"/>
        <bt:Url id="functionFile" DefaultValue="{base}/addons/outlook/commands"/>
      </bt:Urls>
      <bt:ShortStrings>
        <bt:String id="groupLabel" DefaultValue="Halia"/>
        <bt:String id="buttonLabel" DefaultValue="Halia"/>
      </bt:ShortStrings>
      <bt:LongStrings>
        <bt:String id="buttonTip"
                   DefaultValue="Who you are writing to, the house templates, a selection, a visit."/>
      </bt:LongStrings>
    </Resources>
  </VersionOverrides>
</OfficeApp>
"""

_COMMANDS = """<!doctype html><html><head><meta charset="utf-8">
<script src="https://appsforoffice.microsoft.com/lib/1/hosted/office.js"></script>
</head><body></body></html>"""

# Icon sizes Outlook asks for, mapped onto the generated brand marks. The mark is drawn once by
# scripts/build_brand_marks.py; nothing new is drawn here.
_ICONS = {"icon-16.png": "icon-16.png", "icon-32.png": "icon-48.png",
          "icon-64.png": "icon-128.png", "icon-80.png": "icon-128.png",
          "icon-128.png": "icon-128.png"}
_ICON_DIR = Path(__file__).resolve().parent.parent.parent / "docs" / "listing-assets"


def manifest_xml() -> str:
    return _MANIFEST.format(base=_base(), addin_id=config.OUTLOOK_ADDIN_ID)


def register(app) -> None:

    @app.get("/addons/outlook/manifest.xml", include_in_schema=False)
    def outlook_manifest():
        """Public on purpose: sideloading and admin deployment both fetch this unauthenticated."""
        return Response(manifest_xml(), media_type="application/xml",
                        headers={"Cache-Control": "no-store"})

    @app.get("/addons/outlook/taskpane", include_in_schema=False)
    def outlook_taskpane():
        f = _DIR / "taskpane.html"
        if not f.is_file():
            raise HTTPException(404, "Not found")
        return _framed(f.read_text(encoding="utf-8").replace("__BASE__", _base()))

    @app.get("/addons/outlook/taskpane.js", include_in_schema=False)
    def outlook_taskpane_js():
        f = _DIR / "taskpane.js"
        if not f.is_file():
            raise HTTPException(404, "Not found")
        return Response(f.read_text(encoding="utf-8"), media_type="application/javascript",
                        headers={"Cache-Control": "no-store"})

    @app.get("/addons/outlook/commands", include_in_schema=False)
    def outlook_commands():
        return _framed(_COMMANDS)

    @app.get("/addons/outlook/asset/{name}", include_in_schema=False)
    def outlook_asset(name: str):
        src = _ICONS.get(name)
        if not src:
            raise HTTPException(404, "Not found")
        f = _ICON_DIR / src
        if not f.is_file():
            raise HTTPException(404, "Not found")
        return Response(f.read_bytes(), media_type="image/png",
                        headers={"Cache-Control": "public, max-age=86400"})
