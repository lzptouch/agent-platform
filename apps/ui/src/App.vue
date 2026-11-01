<template>
  <!--
    v3：布局职责下沉到 WorkspaceLayout / AdminLayout。
    App 仅保留路由出口，避免全局顶栏与能力复选框污染工作台（计划 §4.2 L-1）。
  -->
  <router-view />
</template>

<script setup lang="ts">
</script>
