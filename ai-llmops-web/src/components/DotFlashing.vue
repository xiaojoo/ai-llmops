<template>
  <div class="h-5 w-5 flex items-center justify-center">
    <div class="dot-flashing"></div>
  </div>
</template>

<style scoped>
.dot-flashing {
  position: relative;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background-color: #667085;
  animation: dot-flashing 1s infinite linear alternate;
  animation-delay: 0.5s;
}

.dot-flashing::before,
.dot-flashing::after {
  content: '';
  position: absolute;
  top: 0;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background-color: #667085;
  animation: dot-flashing 1s infinite linear alternate;
}

.dot-flashing::before {
  left: -10px;
  animation-delay: 0s;
}

.dot-flashing::after {
  left: 10px;
  animation-delay: 1s;
}

@keyframes dot-flashing {
  0% {
    background-color: #667085;
  }

  50%,
  100% {
    background-color: rgba(102, 112, 133, 0.3);
  }
}
</style>
