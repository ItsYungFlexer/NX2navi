"""Exercise the actual scratch-cache and view lifetime code with a mocked Vulkan device.

No game files or GPU required. Set CC to clang and VULKAN_INCLUDE to the Vulkan
headers directory when they are not on the compiler's normal search path.
"""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


def function(path, signature):
    text = (ROOT / path).read_text(encoding='utf-8')
    start = text.index(signature)
    end = text.index('\n}', start) + 2
    return text[start:end]


HARNESS = r'''
#include <vulkan/vulkan.h>
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
typedef void *VmaAllocation;
typedef struct { int usage; } VmaAllocationCreateInfo;
#define VMA_MEMORY_USAGE_AUTO_PREFER_DEVICE 1
typedef struct { void *vma; VkDevice device; } VkCtx;
typedef struct { VkCommandBuffer cb; } VkExec;
static VkCtx ctx;
static VkCtx *vk_ctx(void) { return &ctx; }
static int knob_tm_dispatch(void) { return 1; }
static int created, retired, views_retired, fail_create;
static uintptr_t handle = 100;
static const char *mode;
static const char *cfg_value(const char *name) { (void)name; return mode; }
#define rt_log(...) ((void)0)
static VkResult vmaCreateImage(void *vma, const VkImageCreateInfo *ii,
    const VmaAllocationCreateInfo *ai, VkImage *img, VmaAllocation *a, void *unused) {
    if (fail_create) return VK_ERROR_OUT_OF_DEVICE_MEMORY;
    assert(ii->extent.width && ii->extent.height);
    *img = (VkImage)++handle; *a = (void *)handle; created++;
    return VK_SUCCESS;
}
VKAPI_ATTR void VKAPI_CALL vkCmdPipelineBarrier2(VkCommandBuffer cb, const VkDependencyInfo *d) {
    assert(d->imageMemoryBarrierCount == 1);
    assert(d->pImageMemoryBarriers->oldLayout == VK_IMAGE_LAYOUT_UNDEFINED);
    assert(d->pImageMemoryBarriers->newLayout == VK_IMAGE_LAYOUT_GENERAL);
}
VKAPI_ATTR VkResult VKAPI_CALL vkCreateImageView(VkDevice dev, const VkImageViewCreateInfo *ci,
    const VkAllocationCallbacks *allocator, VkImageView *view) {
    *view = (VkImageView)(uintptr_t)((uintptr_t)ci->image + 10000);
    return VK_SUCCESS;
}
static void vk_defer_view(VkImageView view) { assert(view); views_retired++; }
static struct {
    struct { VkImage img; VkFormat f; VkImageView view; } views[16];
    int nviews;
} TM;
'''

MAIN = r'''
int main(int argc, char **argv) {
    if (argc > 1) {
        mode = argv[1];
        printf("%d\n", pipe_skip_mode());
        return 0;
    }
    VkExec ex = {0};
    VkFormat f = VK_FORMAT_E5B9G9R9_UFLOAT_PACK32;
    VkImage first = fallback_scratch(&ex, 100, 100, f);
    assert(first && tm_view(first, f));
    for (int i = 1; i < 8; i++) {
        VkImage img = fallback_scratch(&ex, 100 + i, 100, f);
        assert(img && tm_view(img, f));
    }
    assert(created == 8 && TM.nviews == 8);
    assert(fallback_scratch(&ex, 100, 100, f) == first); // refresh the oldest entry
    assert(created == 8);
    fail_create = 1;
    assert(!fallback_scratch(&ex, 200, 100, f));
    assert(retired == 0 && views_retired == 0); // failed replacement preserves valid cache
    fail_create = 0;
    for (int i = 0; i < 40; i++) {
        VkImage img = fallback_scratch(&ex, 200 + i, 100, f);
        assert(img && tm_view(img, f));
        assert(TM.nviews == 8); // neither cache can permanently exhaust after resize
        if (i == 0) assert(fallback_scratch(&ex, 100, 100, f) == first);
    }
    assert(created == 48 && retired == 40 && views_retired == 40);
    // Multiple view formats of the same image must all be removed, including after swap-removal.
    VkImage img = TM.views[0].img;
    assert(tm_view(img, VK_FORMAT_R32_UINT));
    assert(TM.nviews == 9);
    vk_tonemap_forget_image(img);
    assert(TM.nviews == 7 && views_retired == 42);
    puts("scratch reuse, allocation failure, eviction and view retirement: ok");
    return 0;
}
'''


class RenderFallbackTest(unittest.TestCase):
    def test_cache_lifetime_and_skip_modes(self):
        draw = 'runtime/vk_exec_draw.c'
        tone = 'runtime/vk_tonemap.c'
        code = HARNESS + function(tone, 'void vk_tonemap_forget_image(')
        code += r'''
static void vk_defer_image(VkImage img, VmaAllocation a) {
    for (int i = 0; i < TM.nviews; i++) assert(TM.views[i].img != img);
    assert(img && a); retired++;
}
'''
        code += function(tone, 'static VkImageView tm_view(')
        code += function(draw, 'static VkImage fallback_scratch(')
        code += function(draw, 'static int pipe_skip_mode(') + MAIN
        with tempfile.TemporaryDirectory() as temp:
            src = Path(temp) / 'fallback.c'
            exe = Path(temp) / 'fallback.exe'
            src.write_text(code, encoding='utf-8')
            cmd = [os.environ.get('CC', 'clang'), '-std=gnu11', str(src), '-o', str(exe)]
            if os.environ.get('VULKAN_INCLUDE'):
                cmd += ['-I', os.environ['VULKAN_INCLUDE']]
            subprocess.run(cmd, check=True, capture_output=True, text=True)
            subprocess.run([str(exe)], check=True)
            for mode, expected in [('none', 3), ('3', 3), ('strict', 0), ('0', 0),
                                   ('any', 1), ('1', 1), ('fullscreen', 2), ('2', 2)]:
                result = subprocess.run([str(exe), mode], check=True, capture_output=True, text=True)
                self.assertEqual(int(result.stdout), expected, mode)


if __name__ == '__main__':
    unittest.main()
