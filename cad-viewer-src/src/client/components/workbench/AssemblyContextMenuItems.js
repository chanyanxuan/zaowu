function AssemblyContextMenuItemLabel({ children }) {
  return <span className="min-w-0 truncate">{children}</span>;
}

export default function AssemblyContextMenuItems({
  Item,
  Separator,
  itemClassName = "text-xs",
  selected = false,
  isolated = false,
  hidden = false,
  actionCount = 1,
  copyReferenceDisabled = false,
  selectDisabled = false,
  showIsolate = true,
  isolateDisabled = false,
  showExitAllIsolate = false,
  exitAllIsolateDisabled = false,
  showHideOther = true,
  hideOtherDisabled = false,
  hideAllDisabled = true,
  hideAllLabel = "显示全部",
  showVisibility = true,
  visibilityDisabled = false,
  showCameraActions = false,
  resetZoomDisabled = false,
  zoomToFitDisabled = false,
  showHideAll = false,
  showExpandCollapse = false,
  expandSelectedDisabled = true,
  collapseSelectedDisabled = true,
  expandAllDisabled = true,
  collapseAllDisabled = true,
  onCopyReference,
  onSelect,
  onIsolate,
  onExitAllIsolate,
  onHideOther,
  onHideAll,
  onToggleVisibility,
  onResetZoom,
  onZoomToFit,
  onExpandSelected,
  onCollapseSelected,
  onExpandAll,
  onCollapseAll
}) {
  const selectLabel = selected ? "取消选择" : "选择";
  const isolateLabel = isolated
    ? "退出隔离"
    : "隔离";
  const visibilityLabel = hidden
    ? "显示"
    : "隐藏";

  return (
    <>
      <Item
        className={itemClassName}
        disabled={copyReferenceDisabled}
        onSelect={onCopyReference}
      >
        <AssemblyContextMenuItemLabel>复制引用</AssemblyContextMenuItemLabel>
      </Item>
      <Separator />
      <Item
        className={itemClassName}
        disabled={selectDisabled}
        onSelect={onSelect}
      >
        <AssemblyContextMenuItemLabel>{selectLabel}</AssemblyContextMenuItemLabel>
      </Item>
      {showIsolate ? (
        <Item
          className={itemClassName}
          disabled={isolateDisabled}
          onSelect={onIsolate}
        >
          <AssemblyContextMenuItemLabel>{isolateLabel}</AssemblyContextMenuItemLabel>
        </Item>
      ) : null}
      {showExitAllIsolate ? (
        <Item
          className={itemClassName}
          disabled={exitAllIsolateDisabled}
          onSelect={onExitAllIsolate}
        >
          <AssemblyContextMenuItemLabel>退出全部隔离</AssemblyContextMenuItemLabel>
        </Item>
      ) : null}
      {showHideOther || showHideAll || showVisibility ? <Separator /> : null}
      {showHideOther ? (
        <Item
          className={itemClassName}
          disabled={hideOtherDisabled}
          onSelect={onHideOther}
        >
          <AssemblyContextMenuItemLabel>隐藏其他</AssemblyContextMenuItemLabel>
        </Item>
      ) : null}
      {showHideAll ? (
        <Item
          className={itemClassName}
          disabled={hideAllDisabled}
          onSelect={onHideAll}
        >
          <AssemblyContextMenuItemLabel>{hideAllLabel}</AssemblyContextMenuItemLabel>
        </Item>
      ) : null}
      {showVisibility ? (
        <Item
          className={itemClassName}
          disabled={visibilityDisabled}
          onSelect={onToggleVisibility}
        >
          <AssemblyContextMenuItemLabel>{visibilityLabel}</AssemblyContextMenuItemLabel>
        </Item>
      ) : null}
      {showCameraActions ? (
        <>
          <Separator />
          <Item
            className={itemClassName}
            disabled={resetZoomDisabled}
            onSelect={onResetZoom}
          >
            <AssemblyContextMenuItemLabel>重置缩放</AssemblyContextMenuItemLabel>
          </Item>
          <Item
            className={itemClassName}
            disabled={zoomToFitDisabled}
            onSelect={onZoomToFit}
          >
            <AssemblyContextMenuItemLabel>缩放适配</AssemblyContextMenuItemLabel>
          </Item>
        </>
      ) : null}
      {showExpandCollapse ? (
        <>
          <Separator />
          <Item
            className={itemClassName}
            disabled={expandSelectedDisabled}
            onSelect={onExpandSelected}
          >
            <AssemblyContextMenuItemLabel>展开</AssemblyContextMenuItemLabel>
          </Item>
          <Item
            className={itemClassName}
            disabled={collapseSelectedDisabled}
            onSelect={onCollapseSelected}
          >
            <AssemblyContextMenuItemLabel>折叠</AssemblyContextMenuItemLabel>
          </Item>
          <Item
            className={itemClassName}
            disabled={expandAllDisabled}
            onSelect={onExpandAll}
          >
            <AssemblyContextMenuItemLabel>全部展开</AssemblyContextMenuItemLabel>
          </Item>
          <Item
            className={itemClassName}
            disabled={collapseAllDisabled}
            onSelect={onCollapseAll}
          >
            <AssemblyContextMenuItemLabel>全部折叠</AssemblyContextMenuItemLabel>
          </Item>
        </>
      ) : null}
    </>
  );
}
